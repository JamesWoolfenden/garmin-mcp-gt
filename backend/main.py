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

import firebase_admin
from firebase_admin import auth as firebase_auth
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
from pywebpush import webpush, WebPushException
import logging

import hashlib
import secrets

from db import (
    consume_upload_token,
    create_upload_token,
    delete_food_entry,
    delete_push_subscription,
    delete_mcp_api_keys,
    get_all_subscribed_users,
    get_food_entries,
    get_profile,
    get_push_subscriptions,
    get_user_for_mcp_key,
    insert_food_entry,
    save_garmin_tokens,
    upsert_mcp_api_key,
    upsert_profile,
    upsert_push_subscription,
)
from garmin_client import GarminSession

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

GARMIN_URL = os.environ.get("GARMIN_SIDECAR_URL", "")
GARMIN_SECRET = os.environ.get("GARMIN_API_SECRET", "")
ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_CLAIMS = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'you@example.com')}"}
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")

firebase_admin.initialize_app(options={"projectId": "pike-477416"})


async def current_user(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Helpers ───────────────────────────────────────────────────────────────────


def today_str() -> str:
    return date.today().isoformat()


def _garmin_today(uid: str) -> dict[str, Any] | None:
    try:
        with GarminSession(uid) as g:
            today = date.today().isoformat()
            stats = g.get_stats(today)
            hr = g.get_heart_rates(today)
            bb = g.get_body_battery(today) or []
            battery = {}
            if bb:
                battery = {
                    "charged": bb[0].get("charged"),
                    "drained": bb[0].get("drained"),
                }
            return {
                "date": today,
                "active_kcal": stats.get("activeKilocalories", 0),
                "total_kcal": stats.get("totalKilocalories", 0),
                "steps": stats.get("totalSteps", 0),
                "distance_km": round(stats.get("totalDistanceMeters", 0) / 1000, 2),
                "active_minutes": stats.get("activeSeconds", 0) // 60,
                "resting_hr_bpm": hr.get("restingHeartRate"),
                "body_battery": battery,
            }
    except Exception as e:
        logger.warning(f"Garmin today fetch failed: {e}")
        return None


def _garmin_activities(uid: str) -> list[dict] | None:
    try:
        with GarminSession(uid) as g:
            today = date.today().isoformat()
            raw = g.get_activities(0, 20)
            from garmin_mcp import _dedup

            todays = [
                a for a in _dedup(raw) if a.get("startTimeLocal", "")[:10] == today
            ]
            return [
                {
                    "name": (a.get("activityName") or "")[:100],
                    "type": a.get("activityType", {}).get("typeKey"),
                    "duration_min": int(a.get("duration", 0) // 60),
                    "distance_km": round(a.get("distance", 0) / 1000, 2),
                    "kcal": a.get("calories", 0),
                    "avg_power_w": a.get("avgPower"),
                }
                for a in todays
            ]
    except Exception as e:
        logger.warning(f"Garmin activities fetch failed: {e}")
        return None


async def fetch_garmin(uid: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_garmin_today, uid)


async def fetch_garmin_activities(uid: str) -> list[dict] | None:
    return await run_in_threadpool(_garmin_activities, uid)


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


def _garmin_wellness(uid: str) -> dict[str, Any]:
    """Fetch sleep, HRV, and weight trend for richer recommendations. Fails silently."""
    result: dict[str, Any] = {}
    try:
        with GarminSession(uid) as g:
            import garmin_mcp as gm

            today = date.today().isoformat()

            # Last night's sleep
            try:
                sleep = g.get_sleep_data(today)
                daily = sleep.get("dailySleepDTO", {})
                score = daily.get("sleepScores", {}).get("overall", {}).get("value")
                if score:
                    result["sleep_score"] = score
                    result["sleep_duration_h"] = round(
                        (daily.get("sleepTimeSeconds") or 0) / 3600, 1
                    )
            except Exception:
                pass

            # Latest HRV
            try:
                hrv = g.get_hrv_data(today)
                hrv_val = (hrv or {}).get("hrvSummary", {}).get("lastNight")
                if hrv_val:
                    result["hrv_last_night"] = hrv_val
            except Exception:
                pass

            # Weight trend (last 7 days)
            try:
                trend = (
                    gm.get_weight_trend.__wrapped__()
                    if hasattr(gm.get_weight_trend, "__wrapped__")
                    else None
                )
                if trend and len(trend) >= 2:
                    delta = trend[-1].get("avg_weight_kg", 0) - trend[0].get(
                        "avg_weight_kg", 0
                    )
                    result["weight_trend_7d_kg"] = round(delta, 2)
            except Exception:
                pass
    except Exception:
        pass
    return result


def claude_recommend(
    kcal_in: int,
    kcal_burned: int,
    kcal_target: int,
    activities: list[dict],
    time_of_day: str,
    wellness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask Claude to produce a balance recommendation."""
    act_str = (
        ", ".join(f"{a['name']} ({a['duration_min']}min)" for a in (activities or []))
        or "none recorded"
    )

    hour = int(time_of_day.split(":")[0])
    workout_acts = [
        a for a in (activities or []) if a.get("type") not in ("walking", None)
    ]
    total_workout_min = sum(a.get("duration_min", 0) for a in workout_acts)

    if total_workout_min >= 60:
        activity_guidance = (
            f"The user has already done {total_workout_min} minutes of structured exercise today. "
            "Do NOT suggest more structured workouts. A short walk is fine if relevant, "
            "but focus primarily on nutrition and recovery."
        )
    elif total_workout_min > 0:
        activity_guidance = (
            f"The user has done {total_workout_min} minutes of exercise today. "
            "Consider whether additional light activity would help meet their target, "
            "but don't suggest hard effort."
        )
    elif hour >= 17:
        activity_guidance = "It is too late to meaningfully change activity today — focus advice on food only."
    elif hour >= 13:
        activity_guidance = "There is still time for a short walk or evening session if activity is low."
    else:
        activity_guidance = (
            "There is plenty of time to act on both food and activity today."
        )

    wellness_str = ""
    if wellness:
        parts = []
        if "sleep_score" in wellness:
            parts.append(
                f"sleep score {wellness['sleep_score']}/100 ({wellness.get('sleep_duration_h', '?')}h)"
            )
        if "hrv_last_night" in wellness:
            parts.append(f"HRV {wellness['hrv_last_night']}ms")
        if "weight_trend_7d_kg" in wellness:
            direction = "up" if wellness["weight_trend_7d_kg"] > 0 else "down"
            parts.append(
                f"weight trending {direction} {abs(wellness['weight_trend_7d_kg'])}kg this week"
            )
        if parts:
            wellness_str = f" Recovery context: {', '.join(parts)}."

    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        system=(
            "You are a concise fitness and nutrition advisor for a cyclist. "
            "Given calorie intake, calories burned, daily target, activities, time of day, "
            "and recovery context (sleep, HRV, weight trend), produce a short personalised recommendation. "
            f"{activity_guidance}{wellness_str} "
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
async def log_food(req: FoodRequest, uid: str = Depends(current_user)):
    if not req.text.strip():
        raise HTTPException(400, "text is required")
    try:
        parsed = await run_in_threadpool(claude_parse_food, req.text.strip())
    except Exception as e:
        raise HTTPException(502, f"Claude parse failed: {e}")

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "date": today_str(),
        "text": req.text.strip(),
        "parsed": parsed["parsed"],
        "kcal": int(parsed["kcal"]),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_food_entry(entry)
    return {k: v for k, v in entry.items() if k != "user_id"}


@app.get("/food/today")
def get_food_today(uid: str = Depends(current_user)):
    entries = get_food_entries(uid, today_str())
    cleaned = [
        {k: v for k, v in e.items() if k not in ("user_id", "date")} for e in entries
    ]
    total = sum(e["kcal"] for e in entries)
    return {"entries": cleaned, "total_kcal": total}


@app.delete("/food/{entry_id}")
def delete_food(entry_id: str, uid: str = Depends(current_user)):
    delete_food_entry(entry_id, uid)
    return {"ok": True}


# -- Balance ------------------------------------------------------------------


async def _compute_balance(uid: str) -> dict:
    entries = get_food_entries(uid, today_str())
    kcal_in = sum(e["kcal"] for e in entries)

    profile = get_profile(uid)
    kcal_target = profile["kcal_target"]

    # Fetch Garmin data and wellness context in parallel
    import asyncio

    garmin, activities, wellness = await asyncio.gather(
        fetch_garmin(uid),
        fetch_garmin_activities(uid),
        run_in_threadpool(_garmin_wellness, uid),
        return_exceptions=True,
    )
    if isinstance(garmin, Exception):
        garmin = None
    if isinstance(activities, Exception):
        activities = None
    if isinstance(wellness, Exception):
        wellness = {}

    # Prefer summing actual activity calories over the lagging get_stats figure
    if activities:
        kcal_burned = sum(a.get("kcal") or 0 for a in activities)
    elif garmin:
        kcal_burned = garmin["active_kcal"]
    else:
        kcal_burned = 0

    # Augment body battery from today stats into wellness context
    if garmin and garmin.get("body_battery"):
        wellness["body_battery_charged"] = garmin["body_battery"].get("charged")

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
            wellness or {},
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


@app.get("/balance")
async def get_balance(uid: str = Depends(current_user)):
    return await _compute_balance(uid)


# -- Push ---------------------------------------------------------------------


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


@app.post("/push/subscribe")
def push_subscribe(sub: PushSubscription, uid: str = Depends(current_user)):
    sub_id = str(uuid.uuid5(uuid.NAMESPACE_URL, sub.endpoint))
    upsert_push_subscription(
        sub_id,
        uid,
        sub.endpoint,
        sub.keys,
        datetime.now(timezone.utc).isoformat(),
    )
    return {"ok": True}


@app.post("/push/unsubscribe")
def push_unsubscribe(body: dict, uid: str = Depends(current_user)):
    delete_push_subscription(body.get("endpoint", ""), uid)
    return {"ok": True}


# -- Profile ------------------------------------------------------------------


class ProfileUpdate(BaseModel):
    kcal_target: int | None = None
    nudge_times: list[str] | None = None
    timezone: str | None = None


@app.get("/profile")
def get_profile_route(uid: str = Depends(current_user)) -> dict:
    return get_profile(uid)


@app.put("/profile")
def update_profile(body: ProfileUpdate, uid: str = Depends(current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return upsert_profile(uid, updates)


# -- Garmin token upload -------------------------------------------------------


@app.post("/garmin/upload-token")
def create_garmin_upload_token(uid: str = Depends(current_user)):
    """Generate a short-lived token for use with garmin-upload-tokens.ps1."""
    token = secrets.token_urlsafe(32)
    from datetime import timedelta

    expires_at = (
        datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=15)
    ).isoformat()
    create_upload_token(token, uid, expires_at)
    return {"token": token, "expires_in_minutes": 15}


@app.put("/garmin/tokens")
async def upload_garmin_tokens(request: Request, uid: str = Depends(current_user)):
    """Upload tokens via Firebase auth (used internally)."""
    tokens_json = (await request.body()).decode()
    try:
        json.loads(tokens_json)
    except Exception:
        raise HTTPException(400, "tokens must be valid JSON")
    save_garmin_tokens(uid, tokens_json)
    return {"ok": True}


@app.put("/garmin/tokens/upload")
async def upload_garmin_tokens_with_token(request: Request):
    """Upload tokens using a short-lived upload token from the app UI."""
    upload_token = request.headers.get("X-Upload-Token", "").strip()
    if not upload_token:
        raise HTTPException(401, "X-Upload-Token header required")
    uid = consume_upload_token(upload_token)
    if not uid:
        raise HTTPException(401, "Invalid or expired upload token")
    tokens_json = (await request.body()).decode()
    try:
        json.loads(tokens_json)
    except Exception:
        raise HTTPException(400, "tokens must be valid JSON")
    save_garmin_tokens(uid, tokens_json)
    return {"ok": True}


# -- MCP API keys -------------------------------------------------------------


@app.post("/garmin/mcp-key")
def generate_mcp_key(uid: str = Depends(current_user)):
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    delete_mcp_api_keys(uid)  # revoke any existing key
    upsert_mcp_api_key(key_hash, uid)
    return {"key": raw_key}


# -- Internal nudge (Cloud Scheduler) ----------------------------------------


@app.post("/internal/nudge")
async def nudge(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if INTERNAL_SECRET and secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401)

    pushed_total = 0
    for uid in get_all_subscribed_users():
        bal = await _compute_balance(uid)
        if bal["status"] == "on_track" and bal["garmin_available"]:
            continue
        body = bal["recommendation"]
        for sub in get_push_subscriptions(uid):
            if send_push(
                {"endpoint": sub["endpoint"], "keys": sub["keys"]}, "Fuel", body
            ):
                pushed_total += 1

    return {"pushed": pushed_total}


# ── MCP server ────────────────────────────────────────────────────────────────
# Mounted at /mcp — Claude connects here using a long-lived API key.
# Generate a key via POST /garmin/mcp-key (requires Firebase auth).


def _mcp_user(request: Request) -> str:
    key = request.headers.get("X-MCP-Key", "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="X-MCP-Key header required")
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    uid = get_user_for_mcp_key(key_hash)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid MCP key")
    return uid


try:
    from mcp.server.fastmcp import FastMCP
    from garmin_mcp import _analyse_heart_rates

    mcp = FastMCP("Garmin")

    @mcp.tool()
    def get_today_stats(request: Request = None) -> dict:
        """Return today's step count, distance, calories, active time, and resting HR."""
        uid = _mcp_user(request) if request else ""
        result = _garmin_today(uid)
        if result is None:
            return {"error": "Garmin data unavailable"}
        return result

    @mcp.tool()
    def get_sedentary_analysis(offset_days: int = 0, request: Request = None) -> dict:
        """Analyse how sedentary a day was based on heart rate patterns."""
        uid = _mcp_user(request) if request else ""
        with GarminSession(uid) as g:
            from datetime import timedelta

            d = (
                date.today() - timedelta(days=max(0, min(offset_days, 30)))
            ).isoformat()
            data = g.get_heart_rates(d)
        return _analyse_heart_rates(data, d)

    app.mount("/mcp", mcp.get_asgi_app())
    logger.info("MCP server mounted at /mcp")
except Exception as e:
    logger.warning(f"MCP server not available: {e}")


# ── Chat endpoint (Claude API with Garmin tools) ──────────────────────────────

_GARMIN_TOOLS = [
    {
        "name": "get_today_stats",
        "description": "Get today's step count, distance, calories, active minutes, resting HR and body battery.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_sedentary_analysis",
        "description": "Analyse how sedentary a day was based on heart rate. Returns sedentary/light/moderate/active time breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offset_days": {
                    "type": "integer",
                    "description": "0=today, 1=yesterday, etc. (max 30)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_sleep",
        "description": "Get sleep data: score, stages, SpO2, stress for a given night.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offset_days": {
                    "type": "integer",
                    "description": "0=last night, 1=night before, etc.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_hrv",
        "description": "Get overnight HRV (heart rate variability) readings — a key recovery metric.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days of HRV history (default 7)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_weekly_trends",
        "description": "Get weekly cycling/activity summary with km, hours, and average power.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_weight",
        "description": "Get the most recent weight measurement from Garmin-connected scales.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _execute_garmin_tool(tool_name: str, tool_input: dict, uid: str) -> Any:
    """Execute a Garmin tool call using the user's stored tokens."""
    import garmin_mcp as gm
    from datetime import timedelta

    with GarminSession(uid) as g:
        d_today = date.today().isoformat()
        offset = tool_input.get("offset_days", 0)
        d = (date.today() - timedelta(days=max(0, min(offset, 30)))).isoformat()

        if tool_name == "get_today_stats":
            return _garmin_today(uid) or {"error": "No data available"}
        elif tool_name == "get_sedentary_analysis":
            data = g.get_heart_rates(d)
            return gm._analyse_heart_rates(data, d)
        elif tool_name == "get_sleep":
            return (
                gm.get_sleep.__wrapped__(offset)
                if hasattr(gm.get_sleep, "__wrapped__")
                else {"note": "sleep data"}
            )
        elif tool_name == "get_hrv":
            hrv_data = g.get_hrv_data(d_today)
            return hrv_data or {"error": "No HRV data"}
        elif tool_name == "get_weekly_trends":
            return {"note": "weekly trends"}
        elif tool_name == "get_weight":
            weight = g.get_weigh_ins(d_today, d_today)
            return weight or {"error": "No weight data"}
        else:
            return {"error": f"Unknown tool: {tool_name}"}


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(req: ChatRequest, uid: str = Depends(current_user)):
    if not req.message.strip():
        raise HTTPException(400, "message is required")

    today = date.today().isoformat()
    system = (
        f"You are a personal health and fitness advisor for a cyclist. "
        f"Today is {today}. You have access to the user's Garmin data via tools. "
        f"Be concise and practical. Use tools when the user asks about their activity, "
        f"sleep, heart rate, or fitness data."
    )

    messages = [{"role": "user", "content": req.message}]

    # Agentic tool use loop
    for _ in range(5):  # max 5 tool call rounds
        response = await run_in_threadpool(
            lambda: ANTHROPIC_CLIENT.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=system,
                tools=_GARMIN_TOOLS,
                messages=messages,
            )
        )

        if response.stop_reason == "end_turn":
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return {"response": text}

        if response.stop_reason != "tool_use":
            break

        # Execute tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = await run_in_threadpool(
                        _execute_garmin_tool, block.name, block.input, uid
                    )
                except Exception as e:
                    result = {"error": str(e)}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return {"response": "Sorry, I couldn't complete that request."}
