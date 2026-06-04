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
    delete_manual_activity,
    delete_push_subscription,
    delete_mcp_api_keys,
    delete_registered_user,
    get_all_subscribed_users,
    get_food_entries,
    get_manual_activities,
    get_profile,
    get_push_subscriptions,
    get_user_for_mcp_key,
    insert_food_entry,
    insert_manual_activity,
    list_registered_users,
    load_chat_history,
    register_user,
    save_chat_message,
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
    allow_origins=[
        "https://fuel.wlfdn.dev",
        "https://pike-477416.web.app",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ────────────────────────────────────────────────────────────────────

ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_CLAIMS = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'you@example.com')}"}
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "")
ADMIN_UID = os.environ.get("ADMIN_UID", "")
_ALLOWED_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

firebase_admin.initialize_app(options={"projectId": "pike-477416"})


async def current_user(request: Request) -> str:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    uid = decoded["uid"]
    email = (decoded.get("email") or "").lower()

    if _ALLOWED_EMAILS and email not in _ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Access not permitted")

    # Record registration on first seen
    register_user(uid, email)
    return uid


async def admin_user(uid: str = Depends(current_user)) -> str:
    if not ADMIN_UID or uid != ADMIN_UID:
        raise HTTPException(status_code=403, detail="Admin access required")
    return uid


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
            current_bb = stats.get("bodyBatteryMostRecentValue")
            if current_bb is not None:
                battery["current"] = current_bb
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
    """Ask Claude to parse a natural language food description into kcal and macros."""
    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=350,
        system=(
            "You are a nutrition estimator. Given a natural language food description, "
            "return ONLY valid JSON with these fields: "
            '"parsed" (string: concise human-readable interpretation using UK portion sizes), '
            '"kcal" (integer), '
            '"carbs_g" (integer: estimated carbohydrates in grams), '
            '"protein_g" (integer: estimated protein in grams), '
            '"fat_g" (integer: estimated fat in grams). '
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
    macros: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Ask Claude to produce a balance recommendation."""
    act_str = (
        ", ".join(f"{a['name']} ({a['duration_min']}min)" for a in (activities or []))
        or "none recorded"
    )

    # Build physiological context — let Claude reason rather than hard-coding rules
    context_parts = [f"Current time: {time_of_day}."]

    workout_acts = [
        a for a in (activities or []) if a.get("type") not in ("walking", None)
    ]
    if workout_acts:
        workout_summary = ", ".join(
            f"{a['name']} {a['duration_min']}min"
            + (f" @ {a['avg_power_w']}W avg" if a.get("avg_power_w") else "")
            for a in workout_acts
        )
        context_parts.append(f"Workouts today: {workout_summary}.")

    if wellness:
        if wellness.get("body_battery_charged") is not None:
            context_parts.append(f"Body battery: {wellness['body_battery_charged']}%.")
        if wellness.get("hrv_last_night"):
            context_parts.append(f"Last night HRV: {wellness['hrv_last_night']}ms.")
        if wellness.get("sleep_score"):
            context_parts.append(f"Sleep score: {wellness['sleep_score']}/100.")

    activity_guidance = (
        " ".join(context_parts)
        + " Use these signals to judge whether more activity is appropriate —"
        " consider workout intensity, fatigue indicators (body battery, HRV), and time remaining in the day."
    )

    # Add weight trend separately (not already in activity_guidance)
    wellness_str = ""
    if wellness and "weight_trend_7d_kg" in wellness:
        direction = "up" if wellness["weight_trend_7d_kg"] > 0 else "down"
        wellness_str = f" Weight trending {direction} {abs(wellness['weight_trend_7d_kg'])}kg this week."

    macros_str = ""
    if macros and any(macros.values()):
        macros_str = (
            f" Diet so far: {macros.get('carbs_g', 0)}g carbs, "
            f"{macros.get('protein_g', 0)}g protein, {macros.get('fat_g', 0)}g fat."
        )

    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=175,
        system=(
            "You are an encouraging fitness and nutrition coach for a cyclist. "
            "Be positive and solution-focused — offer suggestions, not criticism. "
            "Acknowledge what's going well before flagging anything to improve. "
            "Given calorie intake, calories burned, daily target, activities, time of day, "
            "recovery context, and macro breakdown, give a short personalised recommendation. "
            f"{activity_guidance}{wellness_str}{macros_str} "
            'Return ONLY valid JSON: {"status": "on_track"|"over"|"under", "recommendation": string}. '
            "Recommendation must be 1-2 sentences max. No markdown, no preamble. "
            "Do NOT mention any app, website, or URL — the recommendation is read directly in a notification."
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

    macros = {
        "carbs_g": int(parsed.get("carbs_g") or 0),
        "protein_g": int(parsed.get("protein_g") or 0),
        "fat_g": int(parsed.get("fat_g") or 0),
    }
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "date": today_str(),
        "text": req.text.strip(),
        "parsed": parsed["parsed"],
        "kcal": int(parsed["kcal"]),
        "macros_json": json.dumps(macros),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_food_entry(entry)
    result = {k: v for k, v in entry.items() if k not in ("user_id", "macros_json")}
    result.update(macros)
    return result


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


# -- Manual activities --------------------------------------------------------


class ActivityRequest(BaseModel):
    name: str
    kcal: int


@app.post("/activity")
def log_activity(req: ActivityRequest, uid: str = Depends(current_user)):
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "date": today_str(),
        "name": req.name.strip()[:200],
        "kcal": max(0, req.kcal),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_manual_activity(entry)
    return {k: v for k, v in entry.items() if k != "user_id"}


@app.delete("/activity/{entry_id}")
def delete_activity(entry_id: str, uid: str = Depends(current_user)):
    delete_manual_activity(entry_id, uid)
    return {"ok": True}


# -- Balance ------------------------------------------------------------------


def _aggregate_entries(entries: list) -> dict:
    kcal_in = sum(e["kcal"] for e in entries)
    total_carbs = total_protein = total_fat = 0
    for e in entries:
        raw = e.get("macros_json") or "{}"
        m = json.loads(raw)
        if not isinstance(m, dict):
            m = {}
        total_carbs += m.get("carbs_g", 0)
        total_protein += m.get("protein_g", 0)
        total_fat += m.get("fat_g", 0)
    cleaned = [
        {k: v for k, v in e.items() if k not in ("user_id", "date", "macros_json")}
        for e in entries
    ]
    return {
        "kcal_in": kcal_in,
        "macros_today": {
            "carbs_g": total_carbs,
            "protein_g": total_protein,
            "fat_g": total_fat,
        },
        "entries": cleaned,
        "total_kcal": kcal_in,
    }


async def _compute_balance(uid: str, for_date: str | None = None) -> dict:
    target_date = for_date or today_str()
    entries = get_food_entries(uid, target_date)
    agg = _aggregate_entries(entries)
    profile = get_profile(uid)
    kcal_target = profile["kcal_target"]

    manual = [
        {
            "name": a["name"],
            "type": "manual",
            "duration_min": 0,
            "distance_km": 0,
            "kcal": a["kcal"],
            "avg_power_w": None,
            "id": a["id"],
        }
        for a in get_manual_activities(uid, target_date)
    ]

    # For past dates skip live Garmin data and AI recommendation
    if target_date != today_str():
        kcal_burned = sum(a["kcal"] for a in manual)
        return {
            **agg,
            "kcal_burned": kcal_burned,
            "kcal_target": kcal_target,
            "balance": agg["kcal_in"] - kcal_burned,
            "status": "historical",
            "recommendation": None,
            "activity_today": manual,
            "manual_activities": manual,
            "garmin_available": False,
        }

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

    garmin_kcal = 0
    if activities:
        garmin_kcal = sum(a.get("kcal") or 0 for a in activities)
    elif garmin:
        garmin_kcal = garmin["active_kcal"]

    manual_kcal = sum(a["kcal"] for a in manual)
    kcal_burned = garmin_kcal + manual_kcal

    if garmin and garmin.get("body_battery"):
        bb = garmin["body_battery"]
        wellness["body_battery_charged"] = (
            bb.get("current") if bb.get("current") is not None else bb.get("charged")
        )

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

    all_activities = (activities or []) + manual

    hour = datetime.now().hour
    time_of_day = f"{hour:02d}:00"

    try:
        rec = await run_in_threadpool(
            claude_recommend,
            agg["kcal_in"],
            kcal_burned,
            kcal_target,
            all_activities,
            time_of_day,
            wellness or {},
            agg["macros_today"],
        )
    except Exception:
        net = agg["kcal_in"] - kcal_burned
        rec = {
            "status": "on_track" if net <= kcal_target else "over",
            "recommendation": "Activity data unavailable — estimate based on food only.",
        }

    return {
        **agg,
        "kcal_burned": kcal_burned,
        "kcal_target": kcal_target,
        "balance": agg["kcal_in"] - kcal_burned,
        "status": rec["status"],
        "recommendation": rec["recommendation"],
        "activity_today": all_activities,
        "manual_activities": manual,
        "garmin_available": garmin is not None,
    }


@app.get("/balance")
async def get_balance(uid: str = Depends(current_user), date: str | None = None):
    return await _compute_balance(uid, date)


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


# -- Admin -------------------------------------------------------------------


@app.get("/admin/users")
def admin_list_users(uid: str = Depends(admin_user)):
    """List all registered users."""
    return list_registered_users()


@app.delete("/admin/users/{target_uid}")
def admin_delete_user(target_uid: str, uid: str = Depends(admin_user)):
    """Disable a user's Firebase account and remove their profile."""
    try:
        firebase_auth.update_user(target_uid, disabled=True)
    except Exception as e:
        logger.warning(f"Could not disable Firebase user {target_uid}: {e}")
    delete_registered_user(target_uid)
    return {"ok": True, "uid": target_uid}


# -- Internal nudge (Cloud Scheduler) ----------------------------------------


@app.post("/internal/nudge")
async def nudge(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if INTERNAL_SECRET and secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401)

    pushed_total = 0
    for uid in get_all_subscribed_users():
        bal = await _compute_balance(uid)
        kcal_in = round(bal["kcal_in"])
        kcal_burned = round(bal["kcal_burned"])
        net = kcal_in - kcal_burned
        title = f"Fuel · {kcal_in} in · {kcal_burned} burned · {net} net"
        body = bal["recommendation"] or f"{kcal_in} kcal consumed today."
        for sub in get_push_subscriptions(uid):
            if send_push(
                {"endpoint": sub["endpoint"], "keys": sub["keys"]}, title, body
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


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@app.get("/chat/history")
def get_chat_history(uid: str = Depends(current_user)):
    return load_chat_history(uid)


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

    # Build messages with history (last 10 turns) for conversational context
    messages = []
    for h in req.history[-10:]:
        role = h.role if h.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": h.text})
    messages.append({"role": "user", "content": req.message})

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
            # Persist to encrypted chat history
            await run_in_threadpool(save_chat_message, uid, "user", req.message)
            await run_in_threadpool(save_chat_message, uid, "assistant", text)
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
