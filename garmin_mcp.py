"""
Garmin Connect MCP server.
Exposes Garmin health and activity data as tools Claude can call.
Run `garmin-setup` once to authenticate and save session tokens.
"""

import os
import stat
from datetime import date, datetime, timedelta, timezone
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
    current_bb = stats.get("bodyBatteryMostRecentValue")
    if current_bb is not None:
        battery["current"] = current_bb

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


def _weather_code_desc(code: int | None) -> str:
    codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Icy fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        80: "Light showers",
        81: "Showers",
        82: "Heavy showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Thunderstorm with heavy hail",
    }
    return codes.get(code, f"Code {code}") if code is not None else "Unknown"


def _wind_dir(deg: float | None) -> str | None:
    if deg is None:
        return None
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


@mcp.tool()
def get_weather(latitude: float, longitude: float, days: int = 3) -> dict[str, Any]:
    """Get current weather and cycling forecast using OpenMeteo (free, no API key needed).

    Returns current conditions and a daily forecast with cycling-relevant metrics:
    temperature, wind speed/direction, precipitation, and a 'rideable' flag.

    Args:
        latitude: Location latitude (e.g. 51.45 for Reading, UK).
        longitude: Location longitude (e.g. -0.97 for Reading, UK).
        days: Forecast days (1-7, default 3).
    """
    import json as _json
    import urllib.parse
    import urllib.request

    days = max(1, min(days, 7))
    params = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "weather_code",
                    "relative_humidity_2m",
                ]
            ),
            "daily": ",".join(
                [
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "wind_direction_10m_dominant",
                    "weather_code",
                ]
            ),
            "wind_speed_unit": "mph",
            "timezone": "auto",
            "forecast_days": days,
        }
    )
    with urllib.request.urlopen(
        f"https://api.open-meteo.com/v1/forecast?{params}", timeout=10
    ) as resp:
        data = _json.loads(resp.read())

    current = data.get("current", {})
    daily = data.get("daily", {})

    forecast = [
        {
            "date": d,
            "condition": _weather_code_desc(daily["weather_code"][i]),
            "temp_max_c": daily["temperature_2m_max"][i],
            "temp_min_c": daily["temperature_2m_min"][i],
            "precipitation_mm": daily["precipitation_sum"][i],
            "max_wind_mph": daily["wind_speed_10m_max"][i],
            "wind_direction": _wind_dir(daily["wind_direction_10m_dominant"][i]),
            "rideable": (
                daily["precipitation_sum"][i] < 2
                and daily["wind_speed_10m_max"][i] < 25
            ),
        }
        for i, d in enumerate(daily.get("time", []))
    ]

    return {
        "current": {
            "condition": _weather_code_desc(current.get("weather_code")),
            "temp_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_mph": current.get("wind_speed_10m"),
            "wind_direction": _wind_dir(current.get("wind_direction_10m")),
        },
        "forecast": forecast,
    }


@mcp.tool()
def get_activity_weather(activity_id: str) -> dict[str, Any]:
    """Get weather conditions recorded by Garmin during a specific activity.

    Args:
        activity_id: Garmin activity ID (from get_recent_activities).
    """
    raw = client().get_activity_weather(activity_id)
    if not raw:
        return {"error": "No weather data for this activity"}
    return {
        "temp_c": raw.get("temperature"),
        "feels_like_c": raw.get("apparentTemperature"),
        "humidity_pct": raw.get("relativeHumidity"),
        "wind_speed_kph": raw.get("windSpeed"),
        "wind_direction": _wind_dir(raw.get("windDirection")),
        "condition": raw.get("weatherTypePrimary"),
        "precipitation_pct": raw.get("precipitationProbability"),
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
def get_courses(limit: int = 20) -> list[dict[str, Any]]:
    """Return saved courses from Garmin Connect.

    Args:
        limit: Number of courses to return (default 20, max 100).
    """
    limit = max(1, min(limit, 100))
    raw = client().connectapi(
        "/course-service/course", params={"start": 0, "limit": limit}
    )
    if not isinstance(raw, list):
        raw = raw.get("courseList") or [] if isinstance(raw, dict) else []
    return [
        {
            "course_id": c.get("courseId"),
            "name": (c.get("courseName") or "")[:100],
            "type": c.get("activityType", {}).get("typeKey")
            if isinstance(c.get("activityType"), dict)
            else c.get("activityType"),
            "distance_km": round(c.get("distanceInMeters", 0) / 1000, 2)
            if c.get("distanceInMeters")
            else None,
            "elevation_gain_m": c.get("elevationGainInMeters"),
            "created": (c.get("createdDateFormatted") or "")[:10],
        }
        for c in raw
    ]


@mcp.tool()
def get_activity_detail(activity_id: str) -> dict[str, Any]:
    """Return detailed metrics for a specific activity including HR zones, power zones, and bike fit indicators.

    Bike fit interpretation guide (flag concerns when pattern is consistent across rides):
    - left_right_balance: >5% asymmetry sustained = saddle position, cleat, or leg length issue.
      3-5% is borderline; <3% is normal.
    - power_phase (start/end degrees, 0=top dead centre, 180=bottom):
      Normal effective zone is roughly 330-170 deg. A short arc (<160 deg) means dead spots.
      Left/right arc length difference >15 deg suggests asymmetric hip/knee mechanics.
    - platform_center_offset_mm: how far from pedal centre the foot sits. Consistent offset
      one side suggests cleat lateral position or stack height adjustment needed.
    - seated_vs_standing: high standing_pct (>15%) at moderate power can indicate saddle
      too low or too far forward, causing loss of power when seated.
    - avg_cadence_rpm: <75 rpm self-selected = saddle likely too low; >95 with low power
      = saddle possibly too high or too far back.

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
        "avg_power_w": summary.get("averagePower") or summary.get("avgPower"),
        "max_power_w": summary.get("maxPower"),
        "normalized_power_w": summary.get("normalizedPower")
        or summary.get("normPower"),
        "avg_cadence_rpm": summary.get("averageBikeCadence")
        or summary.get("averageBikingCadenceInRevPerMinute")
        or summary.get("averageRunningCadenceInStepsPerMinute"),
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
        "aerobic_training_effect": summary.get("aerobicTrainingEffect"),
        "anaerobic_training_effect": summary.get("anaerobicTrainingEffect"),
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
            "platform_center_offset_mm": summary.get("leftPlatformCenterOffset"),
        }
        if summary.get("leftPowerPhaseStart")
        else None,
        "power_phase_right": {
            "start_deg": summary.get("rightPowerPhaseStart"),
            "end_deg": summary.get("rightPowerPhaseEnd"),
            "peak_start_deg": summary.get("rightPowerPhasePeakStart"),
            "peak_end_deg": summary.get("rightPowerPhasePeakEnd"),
            "platform_center_offset_mm": summary.get("rightPlatformCenterOffset"),
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


def _parse_fit_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Extract TSS, IF, kJ, threshold power, and per-lap breakdown from a FIT zip."""
    import io
    import zipfile

    from garmin_fit_sdk import Decoder, Stream

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        fit_name = next((n for n in z.namelist() if n.endswith(".fit")), None)
        if not fit_name:
            raise ValueError("No .fit file found in download")
        fit_bytes = z.read(fit_name)

    stream = Stream.from_bytes_io(io.BytesIO(fit_bytes))
    decoder = Decoder(stream)
    messages, _ = decoder.read(
        apply_scale_and_offset=True,
        convert_types_to_strings=True,
        expand_sub_fields=True,
        expand_components=True,
    )

    sess = (messages.get("session_mesgs") or [{}])[0]
    laps = messages.get("lap_mesgs") or []

    def _lap_dict(lap: dict, i: int) -> dict:
        elapsed = lap.get("total_elapsed_time") or 0
        return {
            "lap": i + 1,
            "distance_km": round((lap.get("total_distance") or 0) / 1000, 2),
            "duration_min": round(elapsed / 60, 1),
            "avg_power_w": lap.get("avg_power"),
            "normalized_power_w": lap.get("normalized_power"),
            "avg_hr_bpm": lap.get("avg_heart_rate"),
            "avg_cadence_rpm": lap.get("avg_cadence"),
            "total_work_kj": round((lap.get("total_work") or 0) / 1000, 1),
            "avg_left_pco_mm": lap.get("avg_left_pco"),
            "avg_right_pco_mm": lap.get("avg_right_pco"),
            "avg_temperature_c": lap.get("avg_temperature"),
            "total_ascent_m": lap.get("total_ascent"),
        }

    return {
        "tss": sess.get("training_stress_score"),
        "intensity_factor": sess.get("intensity_factor"),
        "total_work_kj": round((sess.get("total_work") or 0) / 1000, 1),
        "threshold_power_w": sess.get("threshold_power"),
        "training_load": sess.get("training_load_peak"),
        "avg_temperature_c": sess.get("avg_temperature"),
        "laps": [_lap_dict(lap, i) for i, lap in enumerate(laps)],
    }


@mcp.tool()
def get_activity_fit(activity_id: str) -> dict[str, Any]:
    """Download the raw FIT file for an activity and return metrics not available via the API.

    Extracts: Training Stress Score (TSS), Intensity Factor (IF), total work (kJ),
    device-configured threshold power (FTP), and a per-lap breakdown with power,
    normalised power, HR, cadence, platform centre offset, and temperature.

    TSS and IF require FTP to be configured on the device. PCO per lap shows whether
    position degrades with fatigue — useful for bike fit analysis across a ride.

    Args:
        activity_id: Garmin activity ID (from get_recent_activities).
    """
    try:
        _id = int(activity_id)
        if _id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(
            f"activity_id must be a positive integer, got: {activity_id!r}"
        )

    zip_bytes = client().download_activity(
        activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
    )
    return _parse_fit_zip(zip_bytes)


def _analyse_heart_rates(data: dict, d: str) -> dict[str, Any]:
    """Pure analysis of raw Garmin HR data for a given local date string."""
    resting = data.get("restingHeartRate") or 60
    readings = [
        (r[0], r[1]) for r in (data.get("heartRateValues") or []) if r[1] is not None
    ]

    if not readings:
        return {"date": d, "error": "No heart rate data available"}

    if len(readings) >= 2:
        # Use only short gaps (≤10 min) so device-off and cross-midnight gaps
        # don't skew the median away from the true sampling interval.
        short_gaps = sorted(
            g
            for g in (
                (readings[i + 1][0] - readings[i][0]) / 60000
                for i in range(len(readings) - 1)
            )
            if 0 < g <= 10
        )
        interval_min = short_gaps[len(short_gaps) // 2] if short_gaps else 1.0
    else:
        interval_min = 1.0

    # Percentage-based thresholds work better for fit users with low resting HR.
    # resting+20 misclassifies brisk walking as sedentary at resting HR ~52.
    light_threshold = round(resting * 1.2)
    moderate_threshold = round(resting * 1.5)
    active_threshold = round(resting * 1.8)

    buckets = {"sedentary": 0.0, "light": 0.0, "moderate": 0.0, "active": 0.0}
    current_streak = 0.0
    max_streak = 0.0
    activity_breaks = 0
    in_sedentary = False
    hourly: dict[int, list[int]] = {}

    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        gmt_start = datetime.strptime(data["startTimestampGMT"], fmt)
        local_start = datetime.strptime(data["startTimestampLocal"], fmt)
        tz_offset = timedelta(seconds=(local_start - gmt_start).total_seconds())
        local_tz = timezone(tz_offset)
    except Exception:
        local_tz = timezone(timedelta(0))

    for ts_ms, bpm in readings:
        local_dt = datetime.fromtimestamp(ts_ms / 1000, tz=local_tz)
        if local_dt.date().isoformat() != d:
            continue
        hour = local_dt.hour
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

    if not hourly:
        return {"date": d, "error": "No heart rate data for this date"}

    if in_sedentary and current_streak >= 10:
        activity_breaks += 1

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
    return _analyse_heart_rates(client().get_heart_rates(d), d)


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
def get_vo2max(days: int = 30) -> list[dict[str, Any]]:
    """Return VO2max and lactate threshold history from Garmin.

    Args:
        days: Number of days to look back (default 30, max 365).
    """
    days = max(1, min(days, 365))
    today = date.today()
    results = []
    c = client()
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        try:
            raw = c.get_max_metrics(d)
            for entry in raw if isinstance(raw, list) else []:
                generic = entry.get("generic") or {}
                vo2 = generic.get("vo2MaxValue")
                lt_hr = generic.get("lactateThresholdHeartRate")
                lt_speed = generic.get("lactateThresholdSpeed")
                if vo2 or lt_hr:
                    results.append(
                        {
                            "date": d,
                            "vo2max": round(vo2, 1) if vo2 else None,
                            "lactate_threshold_hr_bpm": lt_hr,
                            "lactate_threshold_pace_min_per_km": round(
                                1000 / lt_speed / 60, 2
                            )
                            if lt_speed
                            else None,
                        }
                    )
                    break
        except Exception:
            continue
    return results


@mcp.tool()
def get_cycling_ftp() -> dict[str, Any]:
    """Return the user's current cycling Functional Threshold Power (FTP) and W/kg.

    FTP is the highest average power a cyclist can sustain for one hour.
    W/kg (watts per kilogram) is the key cycling performance metric.
    """
    ftp_data = client().get_cycling_ftp()
    ftp = None
    if isinstance(ftp_data, dict):
        ftp = ftp_data.get("functionalThresholdPower")
    elif isinstance(ftp_data, list) and ftp_data:
        ftp = ftp_data[0].get("functionalThresholdPower")

    result: dict[str, Any] = {"ftp_watts": int(ftp) if ftp else None}

    # Try to compute W/kg from latest weight
    try:
        today = date.today()
        start = (today - timedelta(days=30)).isoformat()
        weight_data = client().get_weigh_ins(start, today.isoformat())
        summaries = weight_data.get("dailyWeightSummaries") or []
        if summaries:
            latest = sorted(summaries, key=lambda x: x.get("summaryDate", ""))[-1]
            weight_g = latest.get("latestWeight", {}).get("weight")
            if weight_g and ftp:
                weight_kg = weight_g / 1000
                result["weight_kg"] = round(weight_kg, 2)
                result["w_per_kg"] = round(ftp / weight_kg, 2)
    except Exception:
        pass

    return result


@mcp.tool()
def get_weight(days: int = 30) -> list[dict[str, Any]]:
    """Return weigh-in history from Garmin Index scale for the last N days.

    Includes weight, body fat % (primary body composition metric), muscle mass, body water %, and BMI (included for reference, but less meaningful than body fat % when scale data is available).

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
            answer = input("Re-authenticate now? [y/N] ").strip().lower()
            if answer != "y":
                return
            import shutil

            shutil.rmtree(token_path)
            print("Tokens cleared.")
        else:
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


def _upload_tokens() -> None:
    """CLI entry point: upload local Garmin tokens to a Fuel backend instance."""
    import argparse
    import json as _json
    import urllib.request

    parser = argparse.ArgumentParser(
        description="Upload local Garmin tokens to a Fuel backend."
    )
    parser.add_argument(
        "--token", required=True, help="Upload token from the Fuel app (Connect Garmin)"
    )
    parser.add_argument(
        "--backend",
        default="https://fuel-backend-430943803039.europe-west1.run.app",
        help="Fuel backend URL",
    )
    parser.add_argument("--token-dir", default=TOKEN_DIR, help="Garmin token directory")
    args = parser.parse_args()

    token_path = Path(args.token_dir)
    if not token_path.exists() or not any(token_path.iterdir()):
        print(f"No tokens found in {token_path}. Run garmin-setup first.")
        raise SystemExit(1)

    tokens = {}
    for f in token_path.iterdir():
        try:
            tokens[f.name] = _json.loads(f.read_text())
        except Exception:
            tokens[f.name] = f.read_text()

    body = _json.dumps(tokens).encode()
    req = urllib.request.Request(
        f"{args.backend}/garmin/tokens/upload",
        data=body,
        headers={"X-Upload-Token": args.token, "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                print("Garmin tokens uploaded successfully.")
            else:
                print(f"Upload failed: HTTP {resp.status}")
                raise SystemExit(1)
    except urllib.error.HTTPError as e:
        print(f"Upload failed: HTTP {e.code} — {e.reason}")
        raise SystemExit(1)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
