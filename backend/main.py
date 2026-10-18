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

import asyncio
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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
    create_access_request,
    create_upload_token,
    delete_access_request,
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
    list_access_requests,
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
INTERNAL_SECRET = os.environ["INTERNAL_SECRET"]
ADMIN_UID = os.environ.get("ADMIN_UID", "")
_ALLOWED_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

firebase_admin.initialize_app(options={"projectId": "pike-477416"})

# 5-minute in-process cache for Garmin data (stats, activities, wellness).
# Cloud Run max_instance_count=1 so this is safe; avoids 3 × (KMS + Garmin auth)
# on every food log / balance refresh within the same 5-minute window.
_garmin_cache: dict[str, tuple[float, tuple]] = {}
_GARMIN_TTL = 300


def _verify_firebase_token(request: Request) -> tuple[str, str]:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    return decoded["uid"], (decoded.get("email") or "").lower()


async def current_user(request: Request) -> str:
    uid, email = _verify_firebase_token(request)

    if _ALLOWED_EMAILS and email not in _ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Access not permitted")

    # Record registration on first seen
    register_user(uid, email)
    return uid


async def verified_identity(request: Request) -> tuple[str, str]:
    """Like current_user, but skips the ALLOWED_EMAILS gate. Only for the
    access-request flow, where the caller isn't on the allowlist yet by
    definition -- still requires a real Firebase ID token, so a request
    can't be spoofed with an arbitrary email."""
    return _verify_firebase_token(request)


async def admin_user(uid: str = Depends(current_user)) -> str:
    if not ADMIN_UID or uid != ADMIN_UID:
        raise HTTPException(status_code=403, detail="Admin access required")
    return uid


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_tz(uid: str) -> ZoneInfo:
    tz_name = get_profile(uid).get("timezone") or "Europe/London"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/London")


def user_now(uid: str) -> datetime:
    """Current wall-clock time in the user's own timezone, not server UTC —
    Cloud Run runs in UTC, so date.today()/datetime.now() would put a user's
    post-midnight-BST food log on the wrong day or an hour out in summer."""
    return datetime.now(_user_tz(uid))


def user_today(uid: str) -> date:
    return user_now(uid).date()


def today_str(uid: str) -> str:
    return user_today(uid).isoformat()


def _body_battery_peak(bb_entry: dict) -> float | None:
    """Highest recorded body-battery level for the day, used as a stable
    proxy for the level at wake time — body battery normally peaks
    overnight and drains through the day, so readiness must not use
    'current', which decays the score purely with time since waking (see
    issue #21). Timestamps in the raw time series are large epoch-ms
    numbers, so filtering to values in [0, 100] reliably picks out the
    level regardless of the exact position/shape of each row."""
    values = bb_entry.get("bodyBatteryValuesArray") or []
    levels = [
        v
        for row in values
        if isinstance(row, (list, tuple))
        for v in row
        if isinstance(v, (int, float)) and 0 <= v <= 100
    ]
    return max(levels) if levels else None


def _body_battery_for_readiness(battery: dict) -> float | None:
    """The body-battery value to feed into the readiness score: the
    overnight peak (proxy for level-at-wake), falling back to the day's net
    gain if no time series was available. Never 'current'."""
    if battery.get("peak") is not None:
        return battery["peak"]
    return battery.get("charged")


def _garmin_today_from_session(g, uid: str) -> dict[str, Any]:
    """Core of _garmin_today, for a caller that already has an open Garmin
    session (e.g. the chat tool loop, which reuses one session across calls
    instead of logging in again per tool)."""
    today = user_today(uid).isoformat()
    stats = g.get_stats(today)
    hr = g.get_heart_rates(today)
    bb = g.get_body_battery(today) or []
    battery = {}
    if bb:
        battery = {
            "charged": bb[0].get("charged"),
            "drained": bb[0].get("drained"),
            "peak": _body_battery_peak(bb[0]),
        }
    current_bb = stats.get("bodyBatteryMostRecentValue")
    if current_bb is not None:
        battery["current"] = current_bb
    # Garmin returns these fields as an explicit null, not a missing
    # key, for a day that's only just started (e.g. moments after
    # local midnight) — `.get(key, 0)` only substitutes 0 for a
    # missing key, so `or 0` is needed to also catch the null.
    return {
        "date": today,
        "active_kcal": stats.get("activeKilocalories") or 0,
        "total_kcal": stats.get("totalKilocalories") or 0,
        "steps": stats.get("totalSteps") or 0,
        "distance_km": round((stats.get("totalDistanceMeters") or 0) / 1000, 2),
        "active_minutes": (stats.get("activeSeconds") or 0) // 60,
        "resting_hr_bpm": hr.get("restingHeartRate"),
        "body_battery": battery,
    }


def _garmin_today(uid: str) -> dict[str, Any] | None:
    try:
        with GarminSession(uid) as g:
            return _garmin_today_from_session(g, uid)
    except Exception as e:
        logger.warning(f"Garmin today fetch failed: {e}")
        return None


def _activity_net_kcal(a: dict) -> tuple[int, bool]:
    """Net (active-only) kcal for a Garmin activity, excluding the BMR
    component Garmin bundles into the raw 'calories' field — see issue #22.
    Falls back to gross kcal, flagged as estimated, if bmrCalories is
    missing (e.g. activities synced from a third party)."""
    gross = a.get("calories") or 0
    bmr = a.get("bmrCalories")
    if bmr is None:
        return int(gross), True
    return int(gross - bmr), False


def _garmin_activities(uid: str) -> list[dict] | None:
    try:
        with GarminSession(uid) as g:
            today = user_today(uid).isoformat()
            raw = g.get_activities(0, 20)
            from garmin_mcp import _dedup

            todays = [
                a for a in _dedup(raw) if a.get("startTimeLocal", "")[:10] == today
            ]
            result = []
            for a in todays:
                net_kcal, estimated = _activity_net_kcal(a)
                result.append(
                    {
                        "name": (a.get("activityName") or "")[:100],
                        "type": a.get("activityType", {}).get("typeKey"),
                        "duration_min": int(a.get("duration", 0) // 60),
                        "distance_km": round(a.get("distance", 0) / 1000, 2),
                        "kcal": net_kcal,
                        "kcal_estimated": estimated,
                        "avg_power_w": a.get("avgPower"),
                    }
                )
            return result
    except Exception as e:
        logger.warning(f"Garmin activities fetch failed: {e}")
        return None


def _compute_sleep(g, today: date, offset_days: int = 0) -> dict[str, Any]:
    """Sleep data for a given night, using the caller's already-open Garmin session.

    Mirrors garmin_mcp.get_sleep's output shape, but takes the per-user client
    directly instead of going through that module's global singleton — which
    authenticates from a local token dir this container never populates.

    `today` is the caller's user-local date (see user_today), not server UTC.
    """
    offset_days = max(0, min(offset_days, 365))
    d = (today - timedelta(days=offset_days)).isoformat()
    sleep = g.get_sleep_data(d)
    daily = sleep.get("dailySleepDTO", {})
    return {
        "date": d,
        "sleep_score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
        # Garmin returns these as an explicit null (not a missing key) for a
        # night that hasn't happened yet (e.g. moments after local
        # midnight) — `or 0` catches that; `.get(key, 0)` alone would not.
        "total_sleep_h": round((daily.get("sleepTimeSeconds") or 0) / 3600, 1),
        "deep_min": (daily.get("deepSleepSeconds") or 0) // 60,
        "rem_min": (daily.get("remSleepSeconds") or 0) // 60,
        "light_min": (daily.get("lightSleepSeconds") or 0) // 60,
        "awake_min": (daily.get("awakeSleepSeconds") or 0) // 60,
        "avg_spo2_pct": daily.get("averageSpO2Value"),
        "avg_resting_hr_bpm": daily.get("averageRestingHeartRate"),
        "avg_stress": daily.get("averageStressLevel"),
    }


def _compute_weight_trend(g, today: date, weeks: int = 12) -> list[dict[str, Any]]:
    """Weekly weight/body-fat/muscle-mass averages, using the caller's already-open
    Garmin session (see _compute_sleep for why this can't go through garmin_mcp's
    global client()). `today` is the caller's user-local date (see user_today)."""
    weeks = max(1, min(weeks, 52))
    start = (today - timedelta(days=weeks * 7 + 7)).isoformat()
    data = g.get_weigh_ins(start, today.isoformat())
    by_date: dict[str, dict] = {}
    for s in data.get("dailyWeightSummaries") or []:
        w = s.get("latestWeight", {})
        weight_g = w.get("weight")
        if weight_g:
            by_date[s["summaryDate"]] = {
                "weight_kg": weight_g / 1000,
                "body_fat_pct": w.get("bodyFat"),
                "muscle_mass_kg": w.get("muscleMass") / 1000
                if w.get("muscleMass")
                else None,
            }
    results = []
    for wk in range(weeks - 1, -1, -1):
        week_end = today - timedelta(days=wk * 7)
        week_start = week_end - timedelta(days=6)
        readings = [
            by_date[str(week_start + timedelta(days=dd))]
            for dd in range(7)
            if str(week_start + timedelta(days=dd)) in by_date
        ]
        if not readings:
            continue
        weights = [r["weight_kg"] for r in readings]
        fats = [r["body_fat_pct"] for r in readings if r["body_fat_pct"]]
        muscles = [r["muscle_mass_kg"] for r in readings if r["muscle_mass_kg"]]
        results.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "readings": len(readings),
                "avg_weight_kg": round(sum(weights) / len(weights), 2),
                "avg_body_fat_pct": round(sum(fats) / len(fats), 1) if fats else None,
                "avg_muscle_mass_kg": round(sum(muscles) / len(muscles), 2)
                if muscles
                else None,
            }
        )
    for i in range(1, len(results)):
        results[i]["change_from_prev_week_kg"] = round(
            results[i]["avg_weight_kg"] - results[i - 1]["avg_weight_kg"], 2
        )
    return results


# Garmin's cycling typeKeys aren't all spelled "*cycling*" — a standard road
# ride is "road_biking", not "cycling" (see garmin_mcp.TYPE_PREF, which lists
# "road_biking" separately for the same reason). A plain "cycling" substring
# check would silently drop the single most common ride type.
_CYCLING_TYPE_MARKERS = ("cycl", "bik", "bmx")


def _is_cycling_activity(a: dict) -> bool:
    type_key = (a.get("activityType", {}).get("typeKey") or "").lower()
    return type_key == "virtual_ride" or any(
        marker in type_key for marker in _CYCLING_TYPE_MARKERS
    )


def _recent_rides_from_session(g, limit: int = 5) -> list[dict[str, Any]]:
    """Most recent cycling activities, for the Ride tab's activity list. Uses
    the caller's already-open Garmin session (see _compute_weight_trend)."""
    from garmin_mcp import _dedup

    raw = g.get_activities(0, max(limit * 6, 30))
    cycling = [a for a in _dedup(raw) if _is_cycling_activity(a)][:limit]
    return [
        {
            "activity_id": a.get("activityId"),
            "date": a.get("startTimeLocal", "")[:10],
            "name": (a.get("activityName") or "")[:100],
            "distance_km": round(a.get("distance", 0) / 1000, 2),
            "duration_min": int(a.get("duration", 0) // 60),
            "avg_power_w": a.get("avgPower"),
            "avg_hr_bpm": a.get("averageHR"),
            "elevation_gain_m": a.get("elevationGain"),
            "calories": a.get("calories"),
        }
        for a in cycling
    ]


_KCAL_PER_KG = 7700  # approximation — day-to-day water swings add noise, see below
_CALIBRATION_WINDOW_DAYS = 28
_CALIBRATION_MIN_LOGGED_DAYS = 21
_CALIBRATION_MIN_WEIGH_INS = 8


def _compute_calibration(
    daily_balances: list[float],
    weight_readings: list[tuple[int, float]],
    window_days: int = _CALIBRATION_WINDOW_DAYS,
    min_logged_days: int = _CALIBRATION_MIN_LOGGED_DAYS,
    min_weigh_ins: int = _CALIBRATION_MIN_WEIGH_INS,
) -> dict[str, Any] | None:
    """Compare the weight change logging predicts against the weight change
    that actually happened, to estimate a personal logging bias in
    kcal/day (see issue #24) — food estimates have no error bars and are
    probably off by ±20-30% per entry, so the raw daily balance alone
    overstates its own precision.

    `daily_balances` is one kcal_in - kcal_burned figure per *logged* day
    in the window (a day with nothing logged is simply absent, not zero).
    `weight_readings` is (day_offset, weight_kg) for individual weigh-ins,
    day_offset counted from the start of the window (0) to its end
    (window_days - 1).

    Returns None below the minimum data threshold — with too little data,
    noise (day-to-day water swings of ±0.5kg or more) dominates any
    signal, so showing a number would overstate how certain it is.
    """
    logged_days = len(daily_balances)
    weigh_ins = len(weight_readings)
    if logged_days < min_logged_days or weigh_ins < min_weigh_ins:
        return None

    first_week = [w for offset, w in weight_readings if offset < 7]
    last_week = [w for offset, w in weight_readings if offset >= window_days - 7]
    if not first_week or not last_week:
        return None

    actual_change_kg = sum(last_week) / len(last_week) - sum(first_week) / len(
        first_week
    )
    predicted_change_kg = sum(daily_balances) / _KCAL_PER_KG

    bias = (actual_change_kg - predicted_change_kg) * _KCAL_PER_KG / window_days
    # Rounded to the nearest 50: the window's own noise floor (~140 kcal/day
    # from water-weight swings alone) is far coarser than exact kcal.
    bias_rounded = round(bias / 50) * 50

    return {
        "bias_kcal_per_day": bias_rounded,
        "window_days": window_days,
        "logged_days": logged_days,
        "weigh_ins": weigh_ins,
    }


_VO2MAX_FETCH_WORKERS = 8


def _compute_vo2max(g, today: date, days: int = 30) -> list[dict[str, Any]]:
    """VO2max/lactate-threshold history, using the caller's already-open Garmin
    session (see _compute_weight_trend for why this can't go through
    garmin_mcp's global client()). `today` is the caller's user-local date
    (see user_today).

    get_max_metrics is a per-day Garmin API call with no bulk/range form in
    the client library, so a 90-day window used to mean 90 sequential HTTP
    round trips — the single biggest contributor to /progression's latency.
    Firing them concurrently (bounded) cuts that to roughly
    days / _VO2MAX_FETCH_WORKERS round trips' worth of wall-clock time.
    """
    from concurrent.futures import ThreadPoolExecutor

    days = max(1, min(days, 365))
    all_dates = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    def _fetch_one(d: str) -> dict[str, Any] | None:
        try:
            raw = g.get_max_metrics(d)
            for entry in raw if isinstance(raw, list) else []:
                generic = entry.get("generic") or {}
                vo2 = generic.get("vo2MaxValue")
                lt_hr = generic.get("lactateThresholdHeartRate")
                lt_speed = generic.get("lactateThresholdSpeed")
                if vo2 or lt_hr:
                    return {
                        "date": d,
                        "vo2max": round(vo2, 1) if vo2 else None,
                        "lactate_threshold_hr_bpm": lt_hr,
                        "lactate_threshold_pace_min_per_km": round(
                            1000 / lt_speed / 60, 2
                        )
                        if lt_speed
                        else None,
                    }
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=_VO2MAX_FETCH_WORKERS) as pool:
        # map() preserves input order in its output regardless of which
        # future finishes first, so results stay oldest-to-newest.
        fetched = list(pool.map(_fetch_one, all_dates))
    return [r for r in fetched if r is not None]


async def fetch_garmin(uid: str) -> dict[str, Any] | None:
    return await run_in_threadpool(_garmin_today, uid)


async def fetch_garmin_activities(uid: str) -> list[dict] | None:
    return await run_in_threadpool(_garmin_activities, uid)


def claude_parse_log(text: str) -> dict[str, Any]:
    """Classify text as food or activity, then extract the relevant fields."""
    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=350,
        system=(
            "You are a fitness and nutrition logger. Given free text, decide if it describes "
            "food/drink or a physical activity, then extract the relevant data. "
            "Return ONLY valid JSON. "
            'For food: {"type":"food","parsed":string,"kcal":int,"carbs_g":int,"protein_g":int,"fat_g":int}. '
            'For activity: {"type":"activity","name":string,"kcal":int}. '
            "Use UK portion sizes for food. "
            "No preamble, no markdown, no explanation. Just the JSON object."
        ),
        messages=[{"role": "user", "content": text}],
    )
    raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed


def claude_parse_food(text: str) -> dict[str, Any]:
    result = claude_parse_log(text)
    if result.get("type") == "activity":
        raise ValueError("activity")
    return result


def _garmin_wellness(uid: str) -> dict[str, Any]:
    """Fetch sleep, HRV, and weight trend for richer recommendations. Fails silently."""
    result: dict[str, Any] = {}
    try:
        with GarminSession(uid) as g:
            today_date = user_today(uid)
            today = today_date.isoformat()

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
                summary = (hrv or {}).get("hrvSummary", {})
                hrv_val = summary.get("lastNightAvg")
                if hrv_val:
                    result["hrv_last_night"] = hrv_val
                    result["hrv_status"] = summary.get("status")
                    baseline = summary.get("baseline", {})
                    result["hrv_baseline_low"] = baseline.get("balancedLow")
                    result["hrv_baseline_high"] = baseline.get("balancedUpper")
            except Exception:
                pass

            # Weight trend (this week vs last week)
            try:
                trend = _compute_weight_trend(g, today_date, weeks=2)
                if trend and len(trend) >= 2:
                    delta = trend[-1].get("avg_weight_kg", 0) - trend[0].get(
                        "avg_weight_kg", 0
                    )
                    result["weight_trend_7d_kg"] = round(delta, 2)
                    result["weight_kg"] = trend[-1].get("avg_weight_kg")
            except Exception:
                pass

            # Cycling FTP
            try:
                ftp_data = g.get_cycling_ftp()
                ftp = None
                if isinstance(ftp_data, dict):
                    ftp = ftp_data.get("functionalThresholdPower")
                elif isinstance(ftp_data, list) and ftp_data:
                    ftp = ftp_data[0].get("functionalThresholdPower")
                if ftp:
                    result["ftp_watts"] = int(ftp)
            except Exception:
                pass
    except Exception:
        pass
    return result


# "Balanced" HRV status and "within baseline range" (the numeric fallback
# below) are the same physiological state, so they must score the same —
# see issue #21.
_HRV_BALANCED_SCORE = 80.0

# Garmin's documented HRV Status values. Used ahead of the baseline-range
# fallback below since it's Garmin's own interpretation of the reading
# (accounts for more than a simple range check), when available.
_HRV_STATUS_SCORES = {
    "BALANCED": _HRV_BALANCED_SCORE,
    "UNBALANCED": 45.0,
    "LOW": 35.0,
}


def _compute_readiness(wellness: dict[str, Any]) -> dict[str, Any] | None:
    """Combine sleep, HRV, and body battery into a single daily readiness score.

    Sleep and HRV are weighted higher than body battery: Garmin's body
    battery algorithm already factors in sleep and HRV itself, so weighting
    all three equally would double-count the same underlying signal.

    Returns None when there isn't enough wellness data to say anything
    meaningful (e.g. Garmin not connected, or all per-metric fetches failed).
    """
    components: dict[str, float] = {}

    sleep_score = wellness.get("sleep_score")
    if sleep_score is not None:
        components["sleep"] = float(sleep_score)

    hrv_status = (wellness.get("hrv_status") or "").upper()
    hrv_val = wellness.get("hrv_last_night")
    baseline_low = wellness.get("hrv_baseline_low")
    baseline_high = wellness.get("hrv_baseline_high")
    if hrv_status in _HRV_STATUS_SCORES:
        components["hrv"] = _HRV_STATUS_SCORES[hrv_status]
    elif hrv_val is not None and baseline_low is not None and baseline_high is not None:
        if hrv_val < baseline_low:
            components["hrv"] = 40.0
        elif hrv_val > baseline_high:
            components["hrv"] = 90.0
        else:
            components["hrv"] = _HRV_BALANCED_SCORE

    body_battery = wellness.get("body_battery_charged")
    if body_battery is not None:
        components["body_battery"] = float(body_battery)

    if not components:
        return None

    weights = {"sleep": 0.4, "hrv": 0.4, "body_battery": 0.2}
    total_weight = sum(weights[k] for k in components)
    score = round(sum(components[k] * weights[k] for k in components) / total_weight)

    if score >= 80:
        label = "Fresh"
    elif score >= 60:
        label = "Normal"
    elif score >= 40:
        label = "Tired"
    else:
        label = "Fatigued"

    driver_key = min(components, key=components.get)
    driver_names = {"sleep": "sleep", "hrv": "HRV", "body_battery": "body battery"}

    return {
        "score": score,
        "label": label,
        "driver": f"Lowest signal: {driver_names[driver_key]} ({round(components[driver_key])})",
        "components": {k: round(v) for k, v in components.items()},
    }


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

    # Add weight trend, FTP and W/kg separately
    wellness_str = ""
    if wellness:
        parts = []
        if "weight_trend_7d_kg" in wellness:
            direction = "up" if wellness["weight_trend_7d_kg"] > 0 else "down"
            parts.append(
                f"Weight trending {direction} {abs(wellness['weight_trend_7d_kg'])}kg this week."
            )
        if wellness.get("ftp_watts") and wellness.get("weight_kg"):
            w_per_kg = round(wellness["ftp_watts"] / wellness["weight_kg"], 2)
            parts.append(f"Cycling FTP: {wellness['ftp_watts']}W ({w_per_kg} W/kg).")
        if parts:
            wellness_str = " " + " ".join(parts)

    macros_str = ""
    if macros and any(macros.values()):
        macros_str = (
            f" Diet so far: {macros.get('carbs_g', 0)}g carbs, "
            f"{macros.get('protein_g', 0)}g protein, {macros.get('fat_g', 0)}g fat."
        )

    msg = ANTHROPIC_CLIENT.messages.create(
        model="claude-haiku-4-5-20251001",
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
        "date": today_str(uid),
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
    entries = get_food_entries(uid, today_str(uid))
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
    text: str


@app.post("/activity")
def log_activity(req: ActivityRequest, uid: str = Depends(current_user)):
    parsed = claude_parse_log(req.text.strip())
    entry = {
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "date": today_str(uid),
        "name": str(parsed.get("name", req.text.strip()))[:200],
        "kcal": max(0, int(parsed.get("kcal", 0))),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    insert_manual_activity(entry)
    return {**{k: v for k, v in entry.items() if k != "user_id"}, "type": "activity"}


class LogRequest(BaseModel):
    text: str


@app.post("/log")
async def unified_log(req: LogRequest, uid: str = Depends(current_user)):
    """Single endpoint — Claude decides if the input is food or activity."""
    parsed = await run_in_threadpool(claude_parse_log, req.text.strip())
    now = datetime.now(timezone.utc).isoformat()
    entry_id = str(uuid.uuid4())

    if parsed.get("type") == "activity":
        entry = {
            "id": entry_id,
            "user_id": uid,
            "date": today_str(uid),
            "name": str(parsed.get("name", req.text.strip()))[:200],
            "kcal": max(0, int(parsed.get("kcal", 0))),
            "logged_at": now,
        }
        insert_manual_activity(entry)
        return {
            **{k: v for k, v in entry.items() if k != "user_id"},
            "type": "activity",
        }
    else:
        macros = {
            "carbs_g": int(parsed.get("carbs_g") or 0),
            "protein_g": int(parsed.get("protein_g") or 0),
            "fat_g": int(parsed.get("fat_g") or 0),
        }
        entry = {
            "id": entry_id,
            "user_id": uid,
            "date": today_str(uid),
            "text": req.text.strip(),
            "parsed": str(parsed.get("parsed", req.text.strip()))[:500],
            "kcal": max(0, int(parsed.get("kcal") or 0)),
            "macros_json": json.dumps(macros),
            "logged_at": now,
        }
        insert_food_entry(entry)
        result = {k: v for k, v in entry.items() if k not in ("user_id", "macros_json")}
        return {**result, **macros, "type": "food"}


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


async def _fetch_garmin_data(uid: str) -> tuple:
    """Return (garmin, activities, wellness) with a 5-minute in-process cache.

    The cache key includes the user's own local date, not just uid, so a
    result fetched before midnight (user-local) is never served after —
    see issue #23."""
    cache_key = f"{uid}:{today_str(uid)}"
    cached = _garmin_cache.get(cache_key)
    if cached and time.time() - cached[0] < _GARMIN_TTL:
        return cached[1]

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

    result = (garmin, activities, wellness)
    _garmin_cache[cache_key] = (time.time(), result)
    return result


# Calibration re-fetches up to _CALIBRATION_WINDOW_DAYS days of Garmin daily
# stats, so it's cached for a day rather than the 5 minutes _garmin_cache
# uses — the bias estimate doesn't need to be fresher than that.
_calibration_cache: dict[str, tuple[float, dict | None]] = {}
_CALIBRATION_TTL = 24 * 3600


def _gather_calibration_inputs(
    uid: str, g, today: date, window_days: int = _CALIBRATION_WINDOW_DAYS
) -> tuple[list[float], list[tuple[int, float]]]:
    """Assemble per-day logged balance and individual weigh-ins for the
    calibration window, ending yesterday (today's day is still in
    progress). Burn uses the same net-active-kcal basis as _compute_balance
    (see issue #22)."""
    daily_balances = []
    for i in range(1, window_days + 1):
        d_str = (today - timedelta(days=i)).isoformat()
        kcal_in = _aggregate_entries(get_food_entries(uid, d_str))["kcal_in"]
        if kcal_in <= 0:
            continue  # nothing logged that day
        manual_kcal = sum(a["kcal"] for a in get_manual_activities(uid, d_str))
        try:
            garmin_kcal = g.get_stats(d_str).get("activeKilocalories", 0)
        except Exception:
            continue
        daily_balances.append(kcal_in - (garmin_kcal + manual_kcal))

    window_start = today - timedelta(days=window_days)
    weigh_ins: list[tuple[int, float]] = []
    try:
        data = g.get_weigh_ins(window_start.isoformat(), today.isoformat())
        for s in data.get("dailyWeightSummaries") or []:
            weight_g = (s.get("latestWeight") or {}).get("weight")
            if not weight_g:
                continue
            try:
                d = date.fromisoformat(s["summaryDate"])
            except (KeyError, ValueError):
                continue
            offset = (d - window_start).days
            if 0 <= offset < window_days:
                weigh_ins.append((offset, weight_g / 1000))
    except Exception:
        pass

    return daily_balances, weigh_ins


async def _compute_calibration_cached(uid: str) -> dict | None:
    today = user_today(uid)
    cache_key = f"{uid}:{today.isoformat()}"
    cached = _calibration_cache.get(cache_key)
    if cached and time.time() - cached[0] < _CALIBRATION_TTL:
        return cached[1]

    def _fetch() -> dict | None:
        try:
            with GarminSession(uid) as g:
                daily_balances, weigh_ins = _gather_calibration_inputs(uid, g, today)
        except Exception as e:
            logger.warning(f"Calibration fetch failed for {uid}: {e}")
            return None
        return _compute_calibration(daily_balances, weigh_ins)

    result = await run_in_threadpool(_fetch)
    _calibration_cache[cache_key] = (time.time(), result)
    return result


def _manual_activity_view(a: dict, possible_duplicate: bool = False) -> dict:
    return {
        "name": a["name"],
        "type": "manual",
        "duration_min": 0,
        "distance_km": 0,
        "kcal": a["kcal"],
        "avg_power_w": None,
        "id": a["id"],
        "possible_duplicate": possible_duplicate,
    }


def _is_possible_duplicate(manual: dict, garmin_activities: list[dict] | None) -> bool:
    """Best-effort flag for a manual entry that likely double-counts a Garmin
    activity already synced for the same day — matched on the Garmin
    activity's type or name appearing in the manual entry's free-text name
    (see issue #22). Flagging rather than excluding keeps the call
    reversible/visible; the balance still counts the manual entry."""
    name = (manual.get("name") or "").lower()
    if not name:
        return False
    for a in garmin_activities or []:
        a_type = (a.get("type") or "").replace("_", " ").lower()
        a_name = (a.get("name") or "").lower()
        if a_type and a_type in name:
            return True
        if a_name and a_name in name:
            return True
    return False


async def _compute_balance(uid: str, for_date: str | None = None) -> dict:
    today_val = today_str(uid)
    target_date = for_date or today_val
    entries = get_food_entries(uid, target_date)
    agg = _aggregate_entries(entries)
    profile = get_profile(uid)
    kcal_target = profile["kcal_target"]

    # For past dates skip live Garmin data and AI recommendation
    if target_date != today_val:
        manual = [
            _manual_activity_view(a) for a in get_manual_activities(uid, target_date)
        ]
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
            "readiness": None,
            "calibration": None,
        }

    garmin, activities, wellness = await _fetch_garmin_data(uid)

    manual = [
        _manual_activity_view(a, _is_possible_duplicate(a, activities))
        for a in get_manual_activities(uid, target_date)
    ]

    # Daily activeKilocalories already covers the active portion of any
    # recorded activity plus the rest of the day's movement (steps etc).
    # Summing each activity's gross 'calories' on top would double-count
    # the BMR component baked into that gross figure — see issue #22.
    garmin_kcal = garmin["active_kcal"] if garmin else 0

    manual_kcal = sum(a["kcal"] for a in manual)
    kcal_burned = garmin_kcal + manual_kcal

    if garmin and garmin.get("body_battery"):
        bb = garmin["body_battery"]
        # Readiness uses the overnight peak (wake-time proxy), never the
        # live 'current' value — see issue #21.
        wellness["body_battery_charged"] = _body_battery_for_readiness(bb)
        wellness["body_battery_now"] = bb.get("current")

    readiness = _compute_readiness(wellness or {})

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

    hour = user_now(uid).hour
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

    calibration = await _compute_calibration_cached(uid)

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
        "readiness": readiness,
        "calibration": calibration,
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
    height_cm: int | None = None
    waist_cm: int | None = None
    latitude: float | None = None
    longitude: float | None = None


@app.get("/profile")
def get_profile_route(uid: str = Depends(current_user)) -> dict:
    return get_profile(uid)


@app.put("/profile")
def update_profile(body: ProfileUpdate, uid: str = Depends(current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return upsert_profile(uid, updates)


# -- Cycling forecast (weather rideability + today's readiness) --------------


@app.get("/cycling-forecast")
async def cycling_forecast(uid: str = Depends(current_user)):
    profile = get_profile(uid)
    lat, lon = profile.get("latitude"), profile.get("longitude")
    if lat is None or lon is None:
        return {"error": "location_not_set"}

    from garmin_mcp import get_weather as _get_weather

    try:
        weather = await run_in_threadpool(_get_weather, lat, lon, 7)
    except Exception as e:
        logger.warning(f"Weather fetch failed: {e}")
        return {"error": "weather_unavailable"}

    garmin, _activities, wellness = await _fetch_garmin_data(uid)
    if garmin and garmin.get("body_battery"):
        bb = garmin["body_battery"]
        wellness["body_battery_charged"] = _body_battery_for_readiness(bb)
        wellness["body_battery_now"] = bb.get("current")
    readiness = _compute_readiness(wellness or {})

    today = today_str(uid)
    days = weather.get("forecast", [])
    for day in days:
        day["is_today"] = day["date"] == today
        if day["is_today"]:
            day["readiness"] = readiness

    best_dates = [
        d["date"]
        for d in sorted(
            (d for d in days if d.get("rideable")),
            key=lambda d: (d["max_wind_mph"], d["precipitation_mm"]),
        )
    ][:3]

    return {"days": days, "best_dates": best_dates}


# -- Progression (VO2max + weight trend + recent rides) ----------------------


@app.get("/progression")
async def progression(uid: str = Depends(current_user)):
    try:
        today = user_today(uid)
        with GarminSession(uid) as g:
            weight_trend = await run_in_threadpool(_compute_weight_trend, g, today, 12)
            vo2max = await run_in_threadpool(_compute_vo2max, g, today, 90)
            recent_rides = await run_in_threadpool(_recent_rides_from_session, g, 5)
    except Exception as e:
        logger.warning(f"Progression fetch failed: {e}")
        return {"vo2max": [], "weight_trend": [], "recent_rides": []}

    return {"vo2max": vo2max, "weight_trend": weight_trend, "recent_rides": recent_rides}


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


@app.get("/admin/access-requests")
def admin_list_access_requests(uid: str = Depends(admin_user)):
    """List pending access requests (durable fallback if the push below is missed)."""
    return list_access_requests()


@app.delete("/admin/access-requests/{target_uid}")
def admin_dismiss_access_request(target_uid: str, uid: str = Depends(admin_user)):
    """Dismiss a request -- call after adding the email to ALLOWED_EMAILS, or to reject it."""
    delete_access_request(target_uid)
    return {"ok": True, "uid": target_uid}


# -- Access requests (invite-only allowlist gate) ----------------------------


@app.post("/access-request")
def request_access(identity: tuple[str, str] = Depends(verified_identity)):
    """Called from the "Request access" button on the access-denied screen.
    Requires a real Firebase token (proves email ownership) but deliberately
    does not require ALLOWED_EMAILS membership -- that's the whole point."""
    uid, email = identity
    is_new = create_access_request(uid, email)
    if is_new and ADMIN_UID:
        for sub in get_push_subscriptions(ADMIN_UID):
            send_push(
                {"endpoint": sub["endpoint"], "keys": sub["keys"]},
                "Access request",
                f"{email} wants access to fuel.",
            )
    return {"ok": True}


# -- Internal nudge (Cloud Scheduler) ----------------------------------------


def _current_hour_label(tz_name: str | None) -> str:
    """Current hour as "HH:00" in the given IANA timezone, matching the
    format nudge_times is stored in. Cloud Scheduler fires this endpoint at
    fixed hours (local_scheduler_sa.nudge_hours, Europe/London) regardless of
    any individual user's timezone — this just maps that fixed firing moment
    onto each user's own wall-clock hour, it doesn't change when the
    endpoint is actually called.
    """
    try:
        tz = ZoneInfo(tz_name or "Europe/London")
    except ZoneInfoNotFoundError:
        try:
            tz = ZoneInfo("Europe/London")
        except ZoneInfoNotFoundError:
            # No IANA tz data available at all (shouldn't happen — tzdata is
            # a pinned dependency — but this must never take down the whole
            # nudge loop for every user over one bad lookup). UTC rather than
            # naive localtime, since Cloud Run's OS clock is UTC anyway.
            return datetime.now(timezone.utc).strftime("%H:00")
    return datetime.now(tz).strftime("%H:00")


def _is_weekly_digest_time(tz_name: str | None, nudge_times: list[str]) -> bool:
    """True once a week, on Sunday, at this user's latest configured nudge
    time — so a user with several nudge_times still gets exactly one digest
    rather than one per Sunday slot."""
    if not nudge_times:
        return False
    try:
        tz = ZoneInfo(tz_name or "Europe/London")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Europe/London")
    now = datetime.now(tz)
    if now.weekday() != 6:  # Monday=0 .. Sunday=6
        return False
    return now.strftime("%H:00") == max(nudge_times)


def _compute_weekly_summary(uid: str) -> dict[str, Any] | None:
    """Aggregate the last 7 days of activity/food for the weekly digest.
    Fails silently (returns None) if Garmin is unavailable — the digest is
    skipped for that user rather than sent with garbage data."""
    try:
        today = user_today(uid)
        days = [(today - timedelta(days=i)).isoformat() for i in range(7)]

        kcal_in_total = 0
        for d in days:
            kcal_in_total += _aggregate_entries(get_food_entries(uid, d))["kcal_in"]
            kcal_in_total += sum(a["kcal"] for a in get_manual_activities(uid, d))

        with GarminSession(uid) as g:
            from garmin_mcp import _dedup

            cutoff = days[-1]
            raw = g.get_activities(0, 50)
            week_acts = [
                a for a in _dedup(raw) if a.get("startTimeLocal", "")[:10] >= cutoff
            ]
            distance_km = round(sum(a.get("distance", 0) for a in week_acts) / 1000, 1)
            activity_kcal = sum(a.get("calories") or 0 for a in week_acts)

            trend = _compute_weight_trend(g, today, weeks=2)

        result: dict[str, Any] = {
            "distance_km": distance_km,
            "activity_kcal": activity_kcal,
            "kcal_in_total": kcal_in_total,
            "avg_net_kcal": round((kcal_in_total - activity_kcal) / 7),
            "num_activities": len(week_acts),
        }
        if trend and len(trend) >= 2:
            result["weight_change_kg"] = trend[-1].get("change_from_prev_week_kg")
            result["weight_kg"] = trend[-1].get("avg_weight_kg")
        return result
    except Exception as e:
        logger.warning(f"Weekly digest fetch failed for {uid}: {e}")
        return None


def _format_weekly_digest(summary: dict[str, Any]) -> tuple[str, str]:
    title = f"Fuel · your week · {summary['distance_km']}km"
    parts = [
        f"{summary['num_activities']} activities, {summary['distance_km']}km, "
        f"{summary['activity_kcal']} kcal burned."
    ]
    parts.append(f"Avg net balance: {summary['avg_net_kcal']} kcal/day.")
    if summary.get("weight_change_kg") is not None:
        direction = "up" if summary["weight_change_kg"] > 0 else "down"
        parts.append(f"Weight {direction} {abs(summary['weight_change_kg'])}kg this week.")
    return title, " ".join(parts)


@app.post("/internal/nudge")
async def nudge(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if INTERNAL_SECRET and secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401)

    pushed_total = 0
    for uid in get_all_subscribed_users():
        profile = get_profile(uid)
        nudge_times = profile.get("nudge_times") or []
        if _current_hour_label(profile.get("timezone")) not in nudge_times:
            continue

        if _is_weekly_digest_time(profile.get("timezone"), nudge_times):
            summary = await run_in_threadpool(_compute_weekly_summary, uid)
            if summary is None:
                continue
            title, body = _format_weekly_digest(summary)
        else:
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
                user_today(uid) - timedelta(days=max(0, min(offset_days, 30)))
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
    {
        "name": "get_weather",
        "description": (
            "Get current weather and cycling forecast for a location using OpenMeteo. "
            "Returns temperature, wind speed/direction, precipitation, and a rideable flag per day. "
            "Use when the user asks about weather, whether to ride, or to correlate past performance with conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Location latitude (e.g. 51.45 for Reading, UK)",
                },
                "longitude": {
                    "type": "number",
                    "description": "Location longitude (e.g. -0.97 for Reading, UK)",
                },
                "days": {
                    "type": "integer",
                    "description": "Forecast days 1-7 (default 3)",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_activity_weather",
        "description": "Get weather conditions recorded by Garmin during a specific past activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "Garmin activity ID from get_recent_activities",
                },
            },
            "required": ["activity_id"],
        },
    },
    {
        "name": "get_vo2max",
        "description": "Get VO2max and lactate threshold history from Garmin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default 30, max 365)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_weight_trend",
        "description": "Get weekly rolling weight averages to track fat loss progress without hydration noise.",
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {
                    "type": "integer",
                    "description": "Number of weeks to look back (default 12, max 52)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_cycling_ftp",
        "description": "Get the user's current cycling FTP (functional threshold power) and W/kg.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_recent_activities",
        "description": "Get recent cycling and running activities with distance, duration, HR, power, and elevation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of activities to return (default 10, max 50)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_activity_fit",
        "description": (
            "Download the raw FIT file for an activity and return metrics not in the API: "
            "Training Stress Score (TSS), Intensity Factor (IF), total work (kJ), "
            "device FTP, and a per-lap breakdown with power, NP, HR, cadence, platform centre offset, "
            "and temperature per lap. Use for training load analysis or to see if bike fit degrades with fatigue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "Garmin activity ID from get_recent_activities",
                },
            },
            "required": ["activity_id"],
        },
    },
    {
        "name": "get_activity_detail",
        "description": (
            "Get detailed metrics for a specific activity: HR/power zones, cadence, "
            "left/right power balance, power phase angles, platform centre offset, and seated/standing split. "
            "Use for bike fit analysis — call get_recent_activities first to get activity IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "Garmin activity ID from get_recent_activities",
                }
            },
            "required": ["activity_id"],
        },
    },
    {
        "name": "compare_dual_recordings",
        "description": (
            "Compare HR and power metrics between two recordings of the same ride on different devices. "
            "Use when the user asks how their chest-strap HRM compares to optical HR, or wants to "
            "compare data from two devices recording the same ride."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to compare (YYYY-MM-DD, default today)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_courses",
        "description": "Get saved courses from Garmin Connect with distance, elevation, and activity type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of courses to return (default 20, max 100)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_food_log",
        "description": (
            "Get the user's food diary entries logged in the Fuel app for a given date. "
            "Returns each food item with calories and macros (protein, carbs, fat), "
            "plus daily totals. Use this when the user asks about nutrition, protein intake, "
            "calorie intake, macros, diet, or what they've eaten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (default today)",
                }
            },
            "required": [],
        },
    },
]


def _execute_garmin_tool(tool_name: str, tool_input: dict, uid: str, client) -> Any:
    """Execute a Garmin tool call. `client` is the caller's already-authenticated
    Garmin session (None for DB-only tools), reused across every tool call in a
    chat turn so each call doesn't pay its own login/token-refresh round trip."""
    import garmin_mcp as gm
    from datetime import timedelta

    # DB-only tools — no Garmin session required
    if tool_name == "get_food_log":
        target_date = tool_input.get("date") or today_str(uid)
        entries = get_food_entries(uid, target_date)
        total_kcal = sum(e["kcal"] for e in entries)
        total_protein = total_carbs = total_fat = 0
        items = []
        for e in entries:
            m = json.loads(e.get("macros_json") or "{}")
            total_protein += m.get("protein_g", 0)
            total_carbs += m.get("carbs_g", 0)
            total_fat += m.get("fat_g", 0)
            items.append(
                {
                    "food": e["parsed"],
                    "kcal": e["kcal"],
                    "protein_g": m.get("protein_g", 0),
                    "carbs_g": m.get("carbs_g", 0),
                    "fat_g": m.get("fat_g", 0),
                    "logged_at": e["logged_at"],
                }
            )
        return {
            "date": target_date,
            "entries": items,
            "totals": {
                "kcal": total_kcal,
                "protein_g": total_protein,
                "carbs_g": total_carbs,
                "fat_g": total_fat,
            },
        }

    g = client
    today = user_today(uid)
    d_today = today.isoformat()
    offset = tool_input.get("offset_days", 0)
    d = (today - timedelta(days=max(0, min(offset, 30)))).isoformat()

    if tool_name == "get_today_stats":
        return _garmin_today_from_session(g, uid) or {"error": "No data available"}
    elif tool_name == "get_sedentary_analysis":
        data = g.get_heart_rates(d)
        return gm._analyse_heart_rates(data, d)
    elif tool_name == "get_sleep":
        return _compute_sleep(g, today, offset)
    elif tool_name == "get_hrv":
        hrv_data = g.get_hrv_data(d_today)
        return hrv_data or {"error": "No HRV data"}
    elif tool_name == "get_weekly_trends":
        return {"note": "weekly trends"}
    elif tool_name == "get_weight":
        weight = g.get_weigh_ins(d_today, d_today)
        return weight or {"error": "No weight data"}
    elif tool_name == "get_weather":
        from garmin_mcp import get_weather as _get_weather

        return _get_weather(
            latitude=tool_input["latitude"],
            longitude=tool_input["longitude"],
            days=tool_input.get("days", 3),
        )
    elif tool_name == "get_activity_weather":
        raw = g.get_activity_weather(tool_input["activity_id"])
        if not raw:
            return {"error": "No weather data for this activity"}
        from garmin_mcp import _wind_dir

        return {
            "temp_c": raw.get("temperature"),
            "feels_like_c": raw.get("apparentTemperature"),
            "humidity_pct": raw.get("relativeHumidity"),
            "wind_speed_kph": raw.get("windSpeed"),
            "wind_direction": _wind_dir(raw.get("windDirection")),
            "condition": raw.get("weatherTypePrimary"),
            "precipitation_pct": raw.get("precipitationProbability"),
        }
    elif tool_name == "get_vo2max":
        days_back = max(1, min(tool_input.get("days", 30), 365))
        return _compute_vo2max(g, today, days_back)
    elif tool_name == "get_weight_trend":
        weeks = max(1, min(tool_input.get("weeks", 12), 52))
        return _compute_weight_trend(g, today, weeks)
    elif tool_name == "get_cycling_ftp":
        ftp_data = g.get_cycling_ftp()
        ftp = None
        if isinstance(ftp_data, dict):
            ftp = ftp_data.get("functionalThresholdPower")
        elif isinstance(ftp_data, list) and ftp_data:
            ftp = ftp_data[0].get("functionalThresholdPower")
        result: dict[str, Any] = {"ftp_watts": int(ftp) if ftp else None}
        try:
            start = (today - timedelta(days=30)).isoformat()
            weight_data = g.get_weigh_ins(start, d_today)
            summaries = weight_data.get("dailyWeightSummaries") or []
            if summaries and ftp:
                latest = sorted(summaries, key=lambda x: x.get("summaryDate", ""))[
                    -1
                ]
                weight_g = latest.get("latestWeight", {}).get("weight")
                if weight_g:
                    weight_kg = weight_g / 1000
                    result["weight_kg"] = round(weight_kg, 2)
                    result["w_per_kg"] = round(ftp / weight_kg, 2)
        except Exception:
            pass
        return result
    elif tool_name == "get_recent_activities":
        limit = max(1, min(tool_input.get("limit", 10), 50))
        from garmin_mcp import _dedup

        raw = g.get_activities(0, limit * 2)
        activities = _dedup(raw)[:limit]
        return [
            {
                "activity_id": a.get("activityId"),
                "date": a.get("startTimeLocal", "")[:10],
                "name": (a.get("activityName") or "")[:100],
                "type": a.get("activityType", {}).get("typeKey"),
                "distance_km": round(a.get("distance", 0) / 1000, 2),
                "duration_min": int(a.get("duration", 0) // 60),
                "avg_hr_bpm": a.get("averageHR"),
                "avg_power_w": a.get("avgPower"),
                "elevation_gain_m": a.get("elevationGain"),
                "calories": a.get("calories"),
            }
            for a in activities
        ]
    elif tool_name == "get_activity_fit":
        from garminconnect import Garmin as _Garmin
        from garmin_mcp import _parse_fit_zip

        zip_bytes = g.download_activity(
            tool_input["activity_id"],
            dl_fmt=_Garmin.ActivityDownloadFormat.ORIGINAL,
        )
        return _parse_fit_zip(zip_bytes)
    elif tool_name == "get_activity_detail":
        activity_id = str(tool_input.get("activity_id", ""))
        detail = g.get_activity(activity_id)
        summary = detail.get("summaryDTO", {})
        hr_zones = g.get_activity_hr_in_timezones(activity_id)
        power_zones = g.get_activity_power_in_timezones(activity_id)
        return {
            "activity_id": activity_id,
            "avg_hr_bpm": summary.get("averageHR"),
            "max_hr_bpm": summary.get("maxHR"),
            "avg_power_w": summary.get("averagePower") or summary.get("avgPower"),
            "max_power_w": summary.get("maxPower"),
            "normalized_power_w": summary.get("normalizedPower")
            or summary.get("normPower"),
            "avg_cadence_rpm": summary.get("averageBikeCadence")
            or summary.get("averageBikingCadenceInRevPerMinute"),
            "elevation_gain_m": summary.get("elevationGain"),
            "calories": summary.get("calories"),
            "seated_vs_standing": {
                "avg_seated_power_w": summary.get("averageSeatedPower"),
                "avg_standing_power_w": summary.get("averageStandingPower"),
                "seated_time_s": round(summary["seatedTime"])
                if summary.get("seatedTime")
                else None,
                "standing_time_s": round(summary["standingTime"])
                if summary.get("standingTime")
                else None,
                "standing_pct": round(
                    summary["standingTime"]
                    / (summary["seatedTime"] + summary["standingTime"])
                    * 100,
                    1,
                )
                if summary.get("seatedTime") and summary.get("standingTime")
                else None,
            }
            if summary.get("averageSeatedPower")
            else None,
            "left_right_balance": {
                "left_pct": summary.get("leftBalance"),
                "right_pct": summary.get("rightBalance"),
            }
            if summary.get("leftBalance")
            else None,
            "power_phase_left": {
                "start_deg": summary.get("leftPowerPhaseStart"),
                "end_deg": summary.get("leftPowerPhaseEnd"),
                "peak_start_deg": summary.get("leftPowerPhasePeakStart"),
                "peak_end_deg": summary.get("leftPowerPhasePeakEnd"),
                "platform_center_offset_mm": summary.get(
                    "leftPlatformCenterOffset"
                ),
            }
            if summary.get("leftPowerPhaseStart")
            else None,
            "power_phase_right": {
                "start_deg": summary.get("rightPowerPhaseStart"),
                "end_deg": summary.get("rightPowerPhaseEnd"),
                "peak_start_deg": summary.get("rightPowerPhasePeakStart"),
                "peak_end_deg": summary.get("rightPowerPhasePeakEnd"),
                "platform_center_offset_mm": summary.get(
                    "rightPlatformCenterOffset"
                ),
            }
            if summary.get("rightPowerPhaseStart")
            else None,
            "hr_zones_minutes": {
                f"zone_{z.get('zoneNumber')}": int(z.get("secsInZone", 0) // 60)
                for z in (hr_zones or [])
            },
            "power_zones_minutes": {
                f"zone_{z.get('zoneNumber')}": int(z.get("secsInZone", 0) // 60)
                for z in (power_zones or [])
            },
        }
    elif tool_name == "compare_dual_recordings":
        target = tool_input.get("date") or d_today
        raw = g.get_activities(0, 50)
        day_acts = [a for a in raw if a.get("startTimeLocal", "")[:10] == target]
        if len(day_acts) < 2:
            return {
                "error": f"Fewer than 2 activities on {target} — no dual recording to compare"
            }

        def _slot(a: dict) -> int:
            ts = a.get("startTimeLocal", "")
            try:
                return (int(ts[11:13]) * 60 + int(ts[14:16])) // 10
            except (ValueError, IndexError):
                return -1

        from collections import defaultdict

        slots: dict[int, list] = defaultdict(list)
        for a in day_acts:
            slots[_slot(a)].append(a)
        pair = next((acts[:2] for acts in slots.values() if len(acts) >= 2), None)
        if not pair:
            return {"error": f"No overlapping recordings on {target}"}

        def _metrics(a: dict) -> dict:
            aid = str(a.get("activityId"))
            detail = g.get_activity(aid)
            summary = detail.get("summaryDTO", {})
            hr_zones = g.get_activity_hr_in_timezones(aid)
            return {
                "activity_id": aid,
                "type": a.get("activityType", {}).get("typeKey"),
                "distance_km": round(a.get("distance", 0) / 1000, 2),
                "duration_min": int(a.get("duration", 0) // 60),
                "avg_hr_bpm": summary.get("averageHR"),
                "max_hr_bpm": summary.get("maxHR"),
                "avg_power_w": summary.get("averagePower")
                or summary.get("avgPower"),
                "hr_zones_minutes": {
                    f"zone_{z.get('zoneNumber')}": int(z.get("secsInZone", 0) // 60)
                    for z in (hr_zones or [])
                },
            }

        ma, mb = _metrics(pair[0]), _metrics(pair[1])

        def _diff(key: str):
            va, vb = ma.get(key), mb.get(key)
            return round(va - vb, 1) if va is not None and vb is not None else None

        return {
            "date": target,
            "recording_a": ma,
            "recording_b": mb,
            "differences_a_minus_b": {
                "avg_hr_bpm": _diff("avg_hr_bpm"),
                "max_hr_bpm": _diff("max_hr_bpm"),
                "avg_power_w": _diff("avg_power_w"),
                "distance_km": _diff("distance_km"),
            },
            "interpretation": (
                "Positive difference means recording_a reads higher. "
                "avg_hr_bpm difference indicates optical vs chest-strap HR divergence."
            ),
        }
    elif tool_name == "get_courses":
        from garmin_mcp import get_courses as _get_courses

        return _get_courses(limit=tool_input.get("limit", 20))
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

    today = today_str(uid)
    system = (
        f"You are a personal health and fitness advisor for a cyclist. "
        f"Today is {today}. You have access to the user's Garmin data and food diary via tools. "
        f"Be concise and practical. Use tools when the user asks about their activity, "
        f"sleep, heart rate, fitness data, or nutrition. "
        f"When the user asks about protein, calories, macros, diet, or what they've eaten, "
        f"always call get_food_log first to retrieve their logged food entries. "
        f"For bike fit analysis, call get_recent_activities to find cycling rides with power data, "
        f"then get_activity_detail on 3-5 of them to check cadence, left/right balance, "
        f"power phase, and platform centre offset across multiple rides."
    )

    # Build messages with history (last 10 turns) for conversational context
    messages = []
    for h in req.history[-10:]:
        role = h.role if h.role in ("user", "assistant") else "user"
        messages.append({"role": role, "content": h.text})
    messages.append({"role": "user", "content": req.message})

    # Agentic tool use loop. One Garmin session is opened (lazily, on first
    # need) and reused across every tool call in the turn, rather than each
    # call logging in from scratch — that per-call login/token-refresh round
    # trip was the main reason multi-tool questions (e.g. bike fit analysis)
    # could run past Cloud Run's request timeout.
    garmin_session: GarminSession | None = None
    garmin_client = None
    try:
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
                        if block.name != "get_food_log" and garmin_client is None:
                            garmin_session = GarminSession(uid)
                            garmin_client = await run_in_threadpool(
                                garmin_session.__enter__
                            )
                        result = await run_in_threadpool(
                            _execute_garmin_tool,
                            block.name,
                            block.input,
                            uid,
                            garmin_client,
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
    finally:
        if garmin_session is not None:
            await run_in_threadpool(garmin_session.__exit__, None, None, None)
