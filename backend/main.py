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

import os
import json
import uuid
import httpx
from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import firestore
import anthropic
from pywebpush import webpush, WebPushException
import logging

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

GARMIN_URL = os.environ["GARMIN_SIDECAR_URL"]  # https://fuel.wlfdn.dev
GARMIN_SECRET = os.environ["GARMIN_API_SECRET"]
ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_CLAIMS = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'you@example.com')}"}
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")  # fallback for local dev

db = firestore.Client(project="pike-477416", database="fuel")

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

    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": entry_id,
        "text": req.text.strip(),
        "parsed": parsed["parsed"],
        "kcal": int(parsed["kcal"]),
        "logged_at": now,
    }
    (
        db.collection("users")
        .document(USER_ID)
        .collection("food_log")
        .document(today_str())
        .collection("entries")
        .document(entry_id)
        .set(entry)
    )
    return entry


@app.get("/food/today")
def get_food_today():
    entries_ref = (
        db.collection("users")
        .document(USER_ID)
        .collection("food_log")
        .document(today_str())
        .collection("entries")
    )
    entries = [d.to_dict() for d in entries_ref.stream()]
    entries.sort(key=lambda e: e.get("logged_at", ""), reverse=True)
    total = sum(e.get("kcal", 0) for e in entries)
    return {"entries": entries, "total_kcal": total}


@app.delete("/food/{entry_id}")
def delete_food(entry_id: str):
    (
        db.collection("users")
        .document(USER_ID)
        .collection("food_log")
        .document(today_str())
        .collection("entries")
        .document(entry_id)
        .delete()
    )
    return {"ok": True}


# -- Balance ------------------------------------------------------------------


@app.get("/balance")
async def get_balance():
    food = get_food_today()
    kcal_in = food["total_kcal"]

    profile = get_profile()
    kcal_target = profile["kcal_target"]

    garmin = await fetch_garmin()
    activities = await fetch_garmin_activities()
    kcal_burned = garmin["active_kcal"] if garmin else 0

    # Synthesise a steps entry if no formal activities recorded
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
    (
        db.collection("users")
        .document(USER_ID)
        .collection("push_subscriptions")
        .document(sub_id)
        .set(
            {
                "endpoint": sub.endpoint,
                "keys": sub.keys,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    return {"ok": True}


@app.post("/push/unsubscribe")
def push_unsubscribe(body: dict):
    endpoint = body.get("endpoint", "")
    sub_id = str(uuid.uuid5(uuid.NAMESPACE_URL, endpoint))
    (
        db.collection("users")
        .document(USER_ID)
        .collection("push_subscriptions")
        .document(sub_id)
        .delete()
    )
    return {"ok": True}


# -- Profile ------------------------------------------------------------------

DEFAULT_PROFILE = {
    "kcal_target": 2000,
    "nudge_times": ["08:00", "13:00", "15:00", "20:00"],
    "timezone": "Europe/London",
}


@app.get("/profile")
def get_profile() -> dict:
    doc = db.collection("users").document(USER_ID).get()
    if doc.exists:
        return {**DEFAULT_PROFILE, **doc.to_dict()}
    return DEFAULT_PROFILE


class ProfileUpdate(BaseModel):
    kcal_target: int | None = None
    nudge_times: list[str] | None = None
    timezone: str | None = None


@app.put("/profile")
def update_profile(body: ProfileUpdate):
    db.collection("users").document(USER_ID).set(
        {k: v for k, v in body.model_dump().items() if v is not None}, merge=True
    )
    return get_profile()


# -- Internal nudge (Cloud Scheduler) ----------------------------------------


@app.post("/internal/nudge")
async def nudge(request: Request):
    # Cloud Run verifies OIDC token automatically when --no-allow-unauthenticated.
    # INTERNAL_SECRET env var used for local testing only.
    secret = request.headers.get("X-Internal-Secret", "")
    if INTERNAL_SECRET and secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401)

    bal = await get_balance()

    # Only push if something actionable
    if bal["status"] == "on_track" and bal["garmin_available"]:
        return {"pushed": False, "reason": "on track, no nudge needed"}

    title = "Fuel"
    body = bal["recommendation"]

    subs = (
        db.collection("users")
        .document(USER_ID)
        .collection("push_subscriptions")
        .stream()
    )
    pushed = 0
    for doc in subs:
        s = doc.to_dict()
        ok = send_push({"endpoint": s["endpoint"], "keys": s["keys"]}, title, body)
        if ok:
            pushed += 1

    return {"pushed": pushed, "recommendation": body}
