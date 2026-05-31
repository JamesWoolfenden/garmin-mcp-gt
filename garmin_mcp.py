"""
Garmin Connect MCP server.
Exposes Garmin health and activity data as tools Claude can call.
Run `garmin-setup` once to authenticate and save session tokens.
"""

import os
import stat
from datetime import date, timedelta
from getpass import getpass
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from mcp.server.fastmcp import FastMCP

# Resolve and normalise the token directory (expanduser handles ~, resolve normalises)
_raw_token_dir = os.environ.get("GARMIN_TOKEN_DIR", str(Path.home() / ".garmin_tokens"))
TOKEN_DIR = str(Path(_raw_token_dir).expanduser().resolve())

mcp = FastMCP("Garmin")

_client: Garmin | None = None


def client() -> Garmin:
    global _client
    if _client is None:
        token_path = Path(TOKEN_DIR)
        if not token_path.exists() or not any(token_path.iterdir()):
            raise RuntimeError(
                "No Garmin tokens found. Run `garmin-setup` to authenticate first."
            )
        try:
            _client = Garmin()
            _client.login(TOKEN_DIR)
        except Exception as e:
            _client = None  # reset so next call retries after transient failure
            raise RuntimeError(
                "Failed to connect to Garmin Connect. "
                "Try running `garmin-setup` again to refresh your tokens."
            ) from e
    return _client


TYPE_PREF = {"road_biking": 0, "cycling": 1}


def _dedup(activities: list[dict]) -> list[dict]:
    buckets: dict[tuple, list] = {}
    for a in activities:
        day = a.get("startTimeLocal", "")[:10]
        dist = round(a.get("distance", 0) / 2000) * 2
        buckets.setdefault((day, dist), []).append(a)

    out = []
    for candidates in buckets.values():
        best = min(
            candidates,
            key=lambda a: TYPE_PREF.get(
                a.get("activityType", {}).get("typeKey", ""), 99
            ),
        )
        out.append(best)

    out.sort(key=lambda a: a.get("startTimeLocal", ""), reverse=True)
    return out


@mcp.tool()
def get_today_stats() -> dict[str, Any]:
    """Return today's step count, distance, calories, active time, and resting heart rate."""
    today = date.today().isoformat()
    c = client()
    stats = c.get_stats(today)
    hr = c.get_heart_rates(today)
    bb = c.get_body_battery(today)

    battery = {}
    if bb:
        battery = {"charged": bb[0].get("charged"), "drained": bb[0].get("drained")}

    return {
        "date": today,
        "steps": stats.get("totalSteps"),
        "step_goal": stats.get("dailyStepGoal"),
        "distance_km": round(stats.get("totalDistanceMeters", 0) / 1000, 2),
        "total_kcal": stats.get("totalKilocalories"),
        "active_kcal": stats.get("activeKilocalories"),
        "active_minutes": stats.get("activeSeconds", 0) // 60,
        "resting_hr_bpm": hr.get("restingHeartRate"),
        "body_battery": battery,
    }


@mcp.tool()
def get_recent_activities(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent cycling/running activities, de-duplicated.

    Args:
        limit: Number of activities to return (default 10, max 50).
    """
    limit = max(1, min(limit, 50))
    raw = client().get_activities(0, limit * 2)
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


@mcp.tool()
def get_activity_detail(activity_id: str) -> dict[str, Any]:
    """Return detailed metrics for a specific activity including HR zones and power zones.

    Args:
        activity_id: The Garmin activity ID (from get_recent_activities).
    """
    try:
        _id = int(activity_id)
        if _id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(
            f"activity_id must be a positive integer, got: {activity_id!r}"
        )

    c = client()
    detail = c.get_activity(activity_id)
    summary = detail.get("summaryDTO", {})
    hr_zones = c.get_activity_hr_in_timezones(activity_id)
    power_zones = c.get_activity_power_in_timezones(activity_id)

    return {
        "activity_id": activity_id,
        "avg_hr_bpm": summary.get("averageHR"),
        "max_hr_bpm": summary.get("maxHR"),
        "avg_power_w": summary.get("avgPower"),
        "max_power_w": summary.get("maxPower"),
        "normalized_power_w": summary.get("normPower"),
        "avg_cadence_rpm": summary.get("averageBikingCadenceInRevPerMinute")
        or summary.get("averageRunningCadenceInStepsPerMinute"),
        "elevation_gain_m": summary.get("elevationGain"),
        "calories": summary.get("calories"),
        "aerobic_training_effect": summary.get("aerobicTrainingEffect"),
        "anaerobic_training_effect": summary.get("anaerobicTrainingEffect"),
        "hr_zones_minutes": {
            f"zone_{z.get('zoneNumber')}": int(z.get("secsInZone", 0) // 60)
            for z in (hr_zones or [])
        },
        "power_zones_minutes": {
            f"zone_{z.get('zoneNumber')}": int(z.get("secsInZone", 0) // 60)
            for z in (power_zones or [])
        },
    }


@mcp.tool()
def get_sedentary_analysis(offset_days: int = 0) -> dict[str, Any]:
    """Analyse how sedentary a day was based on heart rate patterns.

    Classifies the day into sedentary, light, moderate, and active time using
    resting HR as the baseline. Also reports longest sedentary streak and an
    hourly average HR breakdown.

    Args:
        offset_days: 0 = today, 1 = yesterday, etc. (max 30).
    """
    offset_days = max(0, min(offset_days, 30))
    d = (date.today() - timedelta(days=offset_days)).isoformat()
    data = client().get_heart_rates(d)

    resting = data.get("restingHeartRate") or 60
    readings = [
        (r[0], r[1]) for r in (data.get("heartRateValues") or []) if r[1] is not None
    ]

    if not readings:
        return {"date": d, "error": "No heart rate data available"}

    interval_min = 1440 / len(readings)  # minutes per reading

    light_threshold = resting + 20
    moderate_threshold = resting + 40
    active_threshold = resting + 60

    buckets = {"sedentary": 0.0, "light": 0.0, "moderate": 0.0, "active": 0.0}
    current_streak = 0.0
    max_streak = 0.0
    activity_breaks = 0
    in_sedentary = False
    hourly: dict[int, list[int]] = {}

    # Derive UTC offset from the GMT vs local start timestamps
    try:
        from datetime import datetime

        fmt = "%Y-%m-%dT%H:%M:%S"
        gmt_start = datetime.strptime(data["startTimestampGMT"], fmt)
        local_start = datetime.strptime(data["startTimestampLocal"], fmt)
        tz_offset_ms = int((local_start - gmt_start).total_seconds()) * 1000
    except Exception:
        tz_offset_ms = 0

    for ts_ms, bpm in readings:
        local_ts = (ts_ms + tz_offset_ms) // 1000
        hour = int(local_ts % 86400 // 3600)
        hourly.setdefault(hour, []).append(bpm)

        if bpm <= light_threshold:
            buckets["sedentary"] += interval_min
            current_streak += interval_min
            max_streak = max(max_streak, current_streak)
            in_sedentary = True
        else:
            if in_sedentary and current_streak >= 10:
                activity_breaks += 1
            current_streak = 0.0
            in_sedentary = False
            if bpm <= moderate_threshold:
                buckets["light"] += interval_min
            elif bpm <= active_threshold:
                buckets["moderate"] += interval_min
            else:
                buckets["active"] += interval_min

    return {
        "date": d,
        "resting_hr_bpm": resting,
        "thresholds_bpm": {
            "sedentary_up_to": light_threshold,
            "light_up_to": moderate_threshold,
            "moderate_up_to": active_threshold,
        },
        "time_hours": {k: round(v / 60, 1) for k, v in buckets.items()},
        "longest_sedentary_streak_min": round(max_streak),
        "activity_breaks_count": activity_breaks,
        "hourly_avg_bpm": {
            f"{h:02d}:00": round(sum(v) / len(v)) for h, v in sorted(hourly.items())
        },
    }


@mcp.tool()
def get_sleep(offset_days: int = 0) -> dict[str, Any]:
    """Return sleep data for a given night.

    Args:
        offset_days: 0 = last night, 1 = night before, etc. (max 365).
    """
    offset_days = max(0, min(offset_days, 365))
    d = (date.today() - timedelta(days=offset_days)).isoformat()
    sleep = client().get_sleep_data(d)
    daily = sleep.get("dailySleepDTO", {})
    return {
        "date": d,
        "sleep_score": daily.get("sleepScores", {}).get("overall", {}).get("value"),
        "total_sleep_h": round(daily.get("sleepTimeSeconds", 0) / 3600, 1),
        "deep_min": daily.get("deepSleepSeconds", 0) // 60,
        "rem_min": daily.get("remSleepSeconds", 0) // 60,
        "light_min": daily.get("lightSleepSeconds", 0) // 60,
        "awake_min": daily.get("awakeSleepSeconds", 0) // 60,
        "avg_spo2_pct": daily.get("averageSpO2Value"),
        "avg_resting_hr_bpm": daily.get("averageRestingHeartRate"),
        "avg_stress": daily.get("averageStressLevel"),
    }


@mcp.tool()
def get_hrv(days: int = 7) -> list[dict[str, Any]]:
    """Return overnight HRV readings for the last N days.

    Args:
        days: Number of days to look back (default 7, max 30).
    """
    days = max(1, min(days, 30))
    today = date.today()
    c = client()
    results = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        data = c.get_hrv_data(d)
        if not data:
            continue
        summary = data.get("hrvSummary", {})
        if not summary:
            continue
        baseline = summary.get("baseline", {})
        results.append(
            {
                "date": d,
                "last_night_avg": summary.get("lastNightAvg"),
                "last_night_5min_high": summary.get("lastNight5MinHigh"),
                "weekly_avg": summary.get("weeklyAvg"),
                "status": summary.get("status"),
                "baseline_low": baseline.get("balancedLow"),
                "baseline_high": baseline.get("balancedUpper"),
            }
        )
    return results


@mcp.tool()
def get_weekly_trends(weeks: int = 8) -> list[dict[str, Any]]:
    """Return weekly cycling summary for the last N weeks.

    Args:
        weeks: Number of weeks to look back (default 8, max 52).
    """
    weeks = max(1, min(weeks, 52))
    today = date.today()
    c = client()
    results = []
    for w in range(weeks - 1, -1, -1):
        week_start = today - timedelta(days=today.weekday() + w * 7)
        week_end = week_start + timedelta(days=6)
        acts = _dedup(
            c.get_activities_by_date(week_start.isoformat(), week_end.isoformat())
        )
        rides = [
            a
            for a in acts
            if "cycling" in a.get("activityType", {}).get("typeKey", "").lower()
            or "biking" in a.get("activityType", {}).get("typeKey", "").lower()
        ]
        results.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "ride_count": len(rides),
                "total_km": round(sum(a.get("distance", 0) for a in rides) / 1000, 1),
                "total_hours": round(
                    sum(a.get("duration", 0) for a in rides) / 3600, 1
                ),
                "avg_power_w": round(
                    sum(a.get("avgPower", 0) or 0 for a in rides if a.get("avgPower"))
                    / max(sum(1 for a in rides if a.get("avgPower")), 1),
                    1,
                )
                if any(a.get("avgPower") for a in rides)
                else None,
            }
        )
    return results


@mcp.tool()
def get_weight(days: int = 30) -> list[dict[str, Any]]:
    """Return weigh-in history from Garmin Index scale for the last N days.

    Includes weight, BMI, body fat %, body water %, muscle mass, and daily change.

    Args:
        days: Number of days to look back (default 30, max 365).
    """
    days = max(1, min(days, 365))
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    data = client().get_weigh_ins(start, today.isoformat())

    results = []
    for s in sorted(
        data.get("dailyWeightSummaries") or [], key=lambda x: x.get("summaryDate", "")
    ):
        w = s.get("latestWeight", {})
        weight_g = w.get("weight")
        muscle_g = w.get("muscleMass")
        bone_g = w.get("boneMass")
        delta_g = w.get("weightDelta")
        results.append(
            {
                "date": s.get("summaryDate"),
                "weight_kg": round(weight_g / 1000, 2) if weight_g else None,
                "bmi": round(w.get("bmi"), 1) if w.get("bmi") else None,
                "body_fat_pct": w.get("bodyFat"),
                "body_water_pct": w.get("bodyWater"),
                "muscle_mass_kg": round(muscle_g / 1000, 2) if muscle_g else None,
                "bone_mass_kg": round(bone_g / 1000, 2) if bone_g else None,
                "change_kg": round(delta_g / 1000, 3) if delta_g else None,
            }
        )
    return results


@mcp.tool()
def get_weight_trend(weeks: int = 12) -> list[dict[str, Any]]:
    """Return weekly weight trend using 7-day rolling averages to smooth daily fluctuations.

    Useful for tracking fat loss progress without being misled by hydration noise.

    Args:
        weeks: Number of weeks to look back (default 12, max 52).
    """
    weeks = max(1, min(weeks, 52))
    today = date.today()
    # Fetch extra days so the first week has enough readings to average
    start = (today - timedelta(days=weeks * 7 + 7)).isoformat()
    data = client().get_weigh_ins(start, today.isoformat())

    # Build a lookup of date -> metrics
    by_date: dict[str, dict] = {}
    for s in data.get("dailyWeightSummaries") or []:
        w = s.get("latestWeight", {})
        weight_g = w.get("weight")
        fat_pct = w.get("bodyFat")
        muscle_g = w.get("muscleMass")
        if weight_g:
            by_date[s["summaryDate"]] = {
                "weight_kg": weight_g / 1000,
                "body_fat_pct": fat_pct if fat_pct else None,
                "muscle_mass_kg": muscle_g / 1000 if muscle_g else None,
            }

    results = []
    for w in range(weeks - 1, -1, -1):
        week_end = today - timedelta(days=w * 7)
        week_start = week_end - timedelta(days=6)

        readings = [
            by_date[str(week_start + timedelta(days=d))]
            for d in range(7)
            if str(week_start + timedelta(days=d)) in by_date
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
                "min_weight_kg": round(min(weights), 2),
                "max_weight_kg": round(max(weights), 2),
                "avg_body_fat_pct": round(sum(fats) / len(fats), 1) if fats else None,
                "avg_muscle_mass_kg": round(sum(muscles) / len(muscles), 2)
                if muscles
                else None,
            }
        )

    # Add week-on-week change
    for i in range(1, len(results)):
        results[i]["change_from_prev_week_kg"] = round(
            results[i]["avg_weight_kg"] - results[i - 1]["avg_weight_kg"], 2
        )

    return results


def _setup() -> None:
    """CLI entry point for initial authentication (`garmin-setup`)."""
    token_path = Path(TOKEN_DIR)
    if token_path.exists() and any(token_path.iterdir()):
        print("Tokens already exist. Testing connection...")
        try:
            c = client()
            c.get_stats(date.today().isoformat())
            print("Connection successful.")
        except Exception as e:
            print(f"Connection failed: {e}")
            print("Delete the token directory and run garmin-setup again.")
        return

    email = input("Garmin email: ")
    password = getpass("Garmin password: ")
    try:
        c = Garmin(email=email, password=password)
        token_path.mkdir(parents=True, exist_ok=True)
        c.login(TOKEN_DIR)
        password = None  # remove reference after use
        token_file = token_path / "garmin_tokens.json"
        if token_file.exists():
            token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        token_path.chmod(stat.S_IRWXU)  # 0o700
        print("Tokens saved and secured.")
    except Exception as e:
        print(f"Authentication failed: {e}")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
