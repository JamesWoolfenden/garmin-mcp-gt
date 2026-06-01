"""
Fuel — FastAPI backend on Cloud Run.

Endpoints:
    GET  /health
    POST /food
    GET  /food/today
    DELETE /food/{id}
    GET  /balance
    POST /push/subscribe
    POST /push/unsubscribe
    GET  /profile
    PUT  /profile
    POST /internal/nudge   (called by Cloud Scheduler)
"""

import json
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
from pywebpush import webpush, WebPushException
import logging

from db import (
    delete_food_entry,
    delete_push_subscription,
    get_food_entries,
    get_profile,
    get_push_subscriptions,
    insert_food_entry,
    upsert_profile,
    upsert_push_subscription,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="fuel-backend", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pike-477416.web.app", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ────────────────────────────────────────────────────────────────────

GARMIN_URL = os.environ["GARMIN_SIDECAR_URL"]
GARMIN_SECRET = os.environ["GARMIN_API_SECRET"]
ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_CLAIMS = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'you@example.com')}"}
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")

# Single user for now — extend to multi-user with Firebase Auth later
USER_ID = "jim"


# ── Helpers ───────────────────────────────────────────────────────────────────


def today_str() -> str:
    return date.today().isoformat()


async def fetch_garmin() -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{GARMIN_URL}/garmin/today",
                headers={"X-API-Secret": GARMIN_SECRET},
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error(f"Garmin fetch error: {e}")
        return None


async def fetch_garmin_activities() -> list[dict] | None:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{GARMIN_URL}/garmin/activities",
                headers={"X-API-Secret": GARMIN_SECRET},
            )
            r.raise_for_status()
            return r.json().get("activities", [])
    except Exception:
        return None


def claude_parse_food(text: str) -> dict[str, Any]:
    """Ask Claude to parse a natural language food description into kcal."""
    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        system=(
            "You are a calorie estimator. Given a natural language food description, "
            "return ONLY valid JSON with two fields: "
            '"parsed" (string: concise human-readable interpretation using UK portion sizes) '
            'and "kcal" (integer: calorie estimate). '
            "No preamble, no markdown, no explanation. Just the JSON object."
        ),
        messages=[{"role": "user", "content": text}],
    )
    raw = msg.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def claude_recommend(
    kcal_in: int,
    kcal_burned: int,
    kcal_target: int,
    activities: list[dict],
    time_of_day: str,
) -> dict[str, Any]:
    """Ask Claude to produce a balance recommendation."""
    act_str = (
        ", ".join(f"{a['name']} ({a['duration_min']}min)" for a in (activities or []))
        or "none recorded"
    )

    hour = int(time_of_day.split(":")[0])
    if hour >= 17:
        activity_guidance = "It is too late to meaningfully change activity today — focus advice on food only."
    elif hour >= 13:
        activity_guidance = "There is still time for a short walk or evening session if activity is low."
    else:
        activity_guidance = (
            "There is plenty of time to act on both food and activity today."
        )

    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        system=(
            "You are a concise fitness and nutrition advisor. "
            "Given calorie intake, calories burned from activity, daily target, "
            "activities done today, and time of day, produce a short recommendation. "
            f"{activity_guidance} "
            'Return ONLY valid JSON: {"status": "on_track"|"over"|"under", "recommendation": string}. '
            "Recommendation must be 1-2 sentences max, practical, not preachy. "
            "No markdown, no preamble."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"kcal_in={kcal_in}, kcal_burned={kcal_burned}, "
                    f"target={kcal_target}, time={time_of_day}, "
                    f"activities today: {act_str}"
                ),
            }
        ],
    )
    raw = msg.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def send_push(subscription: dict, title: str, body: str) -> bool:
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS,
        )
        return True
    except WebPushException:
        return False


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


# -- Food ---------------------------------------------------------------------


class FoodRequest(BaseModel):
    text: str


@app.post("/food")
async def log_food(req: FoodRequest):
    if not req.text.strip():
        raise HTTPException(400, "text is required")
    try:
        parsed = await run_in_threadpool(claude_parse_food, req.text.strip())
    except Exception as e:
        raise HTTPException(502, f"Claude parse failed: {e}")

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": USER_ID,
        "date": today_str(),
        "text": req.text.strip(),
        "parsed": parsed["parsed"],
        "kcal": int(parsed["kcal"]),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_food_entry(entry)
    return {k: v for k, v in entry.items() if k != "user_id"}


@app.get("/food/today")
def get_food_today():
    entries = get_food_entries(USER_ID, today_str())
    cleaned = [
        {k: v for k, v in e.items() if k not in ("user_id", "date")} for e in entries
    ]
    total = sum(e["kcal"] for e in entries)
    return {"entries": cleaned, "total_kcal": total}


@app.delete("/food/{entry_id}")
def delete_food(entry_id: str):
    delete_food_entry(entry_id, USER_ID)
    return {"ok": True}


# -- Balance ------------------------------------------------------------------


@app.get("/balance")
async def get_balance():
    food = get_food_today()
    kcal_in = food["total_kcal"]

    profile = get_profile(USER_ID)
    kcal_target = profile["kcal_target"]

    garmin = await fetch_garmin()
    activities = await fetch_garmin_activities()
    kcal_burned = garmin["active_kcal"] if garmin else 0

    if garmin and not activities:
        activities = [
            {
                "name": f"{garmin['steps']:,} steps",
                "type": "walking",
                "duration_min": garmin["active_minutes"],
                "distance_km": garmin["distance_km"],
                "kcal": garmin["active_kcal"],
                "avg_power_w": None,
            }
        ]

    hour = datetime.now().hour
    time_of_day = f"{hour:02d}:00"

    try:
        rec = await run_in_threadpool(
            claude_recommend,
            kcal_in,
            kcal_burned,
            kcal_target,
            activities or [],
            time_of_day,
        )
    except Exception:
        net = kcal_in - kcal_burned
        rec = {
            "status": "on_track" if net <= kcal_target else "over",
            "recommendation": "Activity data unavailable — estimate based on food only.",
        }

    return {
        "kcal_in": kcal_in,
        "kcal_burned": kcal_burned,
        "kcal_target": kcal_target,
        "balance": kcal_in - kcal_burned,
        "status": rec["status"],
        "recommendation": rec["recommendation"],
        "activity_today": activities or [],
        "garmin_available": garmin is not None,
    }


# -- Push ---------------------------------------------------------------------


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


@app.post("/push/subscribe")
def push_subscribe(sub: PushSubscription):
    sub_id = str(uuid.uuid5(uuid.NAMESPACE_URL, sub.endpoint))
    upsert_push_subscription(
        sub_id,
        USER_ID,
        sub.endpoint,
        sub.keys,
        datetime.now(timezone.utc).isoformat(),
    )
    return {"ok": True}


@app.post("/push/unsubscribe")
def push_unsubscribe(body: dict):
    delete_push_subscription(body.get("endpoint", ""), USER_ID)
    return {"ok": True}


# -- Profile ------------------------------------------------------------------


class ProfileUpdate(BaseModel):
    kcal_target: int | None = None
    nudge_times: list[str] | None = None
    timezone: str | None = None


@app.get("/profile")
def get_profile_route() -> dict:
    return get_profile(USER_ID)


@app.put("/profile")
def update_profile(body: ProfileUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return upsert_profile(USER_ID, updates)


# -- Internal nudge (Cloud Scheduler) ----------------------------------------


@app.post("/internal/nudge")
async def nudge(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if INTERNAL_SECRET and secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401)

    bal = await get_balance()

    if bal["status"] == "on_track" and bal["garmin_available"]:
        return {"pushed": False, "reason": "on track, no nudge needed"}

    title = "Fuel"
    body = bal["recommendation"]

    pushed = 0
    for sub in get_push_subscriptions(USER_ID):
        if send_push({"endpoint": sub["endpoint"], "keys": sub["keys"]}, title, body):
            pushed += 1

    return {"pushed": pushed, "recommendation": body}
