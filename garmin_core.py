"""Pure Garmin helpers shared by the stdio MCP server (garmin_mcp.py) and the
backend. Deliberately free of the mcp library and of any global Garmin client,
so an mcp upgrade can't break backend endpoints that only need these."""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

TYPE_PREF = {"road_biking": 0, "cycling": 1}


def _dedup(activities: list[dict]) -> list[dict]:
    def _interval(a: dict):
        try:
            start = datetime.fromisoformat(a.get("startTimeLocal", ""))
        except ValueError:
            return None, None
        end = start + timedelta(seconds=a.get("duration", 0))
        return start, end

    def _overlaps(a: dict, b: dict) -> bool:
        s1, e1 = _interval(a)
        s2, e2 = _interval(b)
        if not (s1 and s2):
            return False
        return s1 < e2 and s2 < e1

    sorted_acts = sorted(activities, key=lambda a: a.get("startTimeLocal", ""))
    groups: list[list[dict]] = []

    for a in sorted_acts:
        merged = False
        for g in groups:
            if any(_overlaps(a, member) for member in g):
                g.append(a)
                merged = True
                break
        if not merged:
            groups.append([a])

    out = []
    for candidates in groups:
        best = max(candidates, key=lambda a: a.get("duration", 0))
        out.append(best)

    out.sort(key=lambda a: a.get("startTimeLocal", ""), reverse=True)
    return out


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


def _clothing_advice(
    feels_like_c: float | None,
    wind_mph: float | None,
    precipitation_mm: float | None,
) -> list[str]:
    """Rule-based cycling kit advice for a given set of conditions.

    Thresholds are feels-like (wind-chill-adjusted) temperature, not raw
    temperature, since that's what actually determines how cold a ride feels.
    """
    advice: list[str] = []

    if feels_like_c is not None:
        if feels_like_c < 0:
            advice.append(
                "Below freezing — full winter kit: thermal base layer, "
                "winter jacket, thermal tights, lobster mitts or thick gloves, "
                "neck warmer, toe covers."
            )
        elif feels_like_c < 5:
            advice.append(
                "Cold — thermal tights, long-sleeve thermal jersey + jacket, "
                "full-finger winter gloves, buff or neck warmer, shoe covers."
            )
        elif feels_like_c < 10:
            advice.append(
                "Chilly — leg/knee warmers, long-sleeve jersey + light jacket, "
                "full-finger gloves."
            )
        elif feels_like_c < 15:
            advice.append(
                "Cool — arm/leg warmers or a light long-sleeve layer over a jersey."
            )
        elif feels_like_c < 20:
            advice.append(
                "Mild — shorts and a light long-sleeve or short-sleeve jersey."
            )
        else:
            advice.append("Warm — shorts, short-sleeve jersey.")

    if wind_mph is not None and wind_mph >= 25:
        advice.append(
            "Very windy — exposed routes will be hard going; consider an "
            "indoor session or a sheltered route instead."
        )
    elif wind_mph is not None and wind_mph >= 15:
        advice.append("Windy — a windproof gilet or jacket is worth packing.")

    if precipitation_mm is not None and precipitation_mm > 0:
        advice.append(
            "Wet roads expected — mudguards, a waterproof layer, and "
            "lights for reduced visibility."
        )

    return advice


def get_weather(latitude: float, longitude: float, days: int = 3) -> dict[str, Any]:
    """Get current weather and cycling forecast using OpenMeteo (free, no API key needed).

    Returns current conditions and a daily forecast with cycling-relevant metrics:
    temperature, feels-like temperature, wind speed/direction, precipitation,
    a 'rideable' flag, rule-based clothing/kit advice, and an hour-by-hour
    breakdown for each day (temp, feels-like, wind, precipitation chance).

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
                    "apparent_temperature_max",
                    "apparent_temperature_min",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "wind_direction_10m_dominant",
                    "weather_code",
                ]
            ),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "apparent_temperature",
                    "precipitation_probability",
                    "wind_speed_10m",
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
    hourly = data.get("hourly", {})

    # Open-Meteo returns one flat hourly series for the whole window (e.g. 7 days
    # of "2024-01-01T00:00" timestamps), not grouped by day — bucket by date so
    # each forecast day can carry its own hour-by-hour breakdown.
    hourly_by_date: dict[str, list[dict[str, Any]]] = {}
    for i, ts in enumerate(hourly.get("time", [])):
        hourly_by_date.setdefault(ts[:10], []).append(
            {
                "time": ts[11:16],
                "temp_c": hourly["temperature_2m"][i],
                "feels_like_c": hourly["apparent_temperature"][i],
                "precipitation_chance_pct": hourly["precipitation_probability"][i],
                "wind_mph": hourly["wind_speed_10m"][i],
                "condition": _weather_code_desc(hourly["weather_code"][i]),
            }
        )

    forecast = []
    for i, d in enumerate(daily.get("time", [])):
        feels_like_max = daily["apparent_temperature_max"][i]
        feels_like_min = daily["apparent_temperature_min"][i]
        # Average of the day's feels-like range as a stand-in for "typical
        # daytime feel" — the daily max/min alone skew toward midday peak or
        # overnight low, neither of which represents a typical ride window.
        feels_like_avg = round((feels_like_max + feels_like_min) / 2, 1)
        wind_mph = daily["wind_speed_10m_max"][i]
        precip_mm = daily["precipitation_sum"][i]
        forecast.append(
            {
                "date": d,
                "condition": _weather_code_desc(daily["weather_code"][i]),
                "temp_max_c": daily["temperature_2m_max"][i],
                "temp_min_c": daily["temperature_2m_min"][i],
                "feels_like_max_c": feels_like_max,
                "feels_like_min_c": feels_like_min,
                "precipitation_mm": precip_mm,
                "max_wind_mph": wind_mph,
                "wind_direction": _wind_dir(daily["wind_direction_10m_dominant"][i]),
                "rideable": precip_mm < 2 and wind_mph < 25,
                "clothing_advice": _clothing_advice(
                    feels_like_avg, wind_mph, precip_mm
                ),
                "hourly": hourly_by_date.get(d, []),
            }
        )

    return {
        "current": {
            "condition": _weather_code_desc(current.get("weather_code")),
            "temp_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_mph": current.get("wind_speed_10m"),
            "wind_direction": _wind_dir(current.get("wind_direction_10m")),
            "clothing_advice": _clothing_advice(
                current.get("apparent_temperature"),
                current.get("wind_speed_10m"),
                current.get("precipitation"),
            ),
        },
        "forecast": forecast,
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


def _training_load_series(
    acts: list[dict], today: date, days: int, ftp: int | None, resting_hr: int | None
) -> list[dict]:
    """Pure computation: per-day load -> CTL/ATL/TSB (PMC) over the window. Shared by
    get_training_load and the backend's per-user equivalent. `today` is the caller's
    local date, not necessarily the server's (see _compute_vo2max in backend/main.py)."""
    start = today - timedelta(days=days - 1)
    daily_load: dict[str, float] = {
        (start + timedelta(days=i)).isoformat(): 0.0 for i in range(days)
    }

    for a in acts:
        type_key = a.get("activityType", {}).get("typeKey", "").lower()
        if not ("cycling" in type_key or "biking" in type_key or "running" in type_key):
            continue
        d = a.get("startTimeLocal", "")[:10]
        if d not in daily_load:
            continue
        duration_h = a.get("duration", 0) / 3600
        avg_power = a.get("avgPower")
        avg_hr = a.get("averageHR")
        if avg_power and ftp:
            intensity = avg_power / ftp
            load = duration_h * intensity**2 * 100
        elif avg_hr and resting_hr and avg_hr > resting_hr:
            # HR-based fallback (TRIMP-lite) for activities with no power meter.
            # Scaled so ~1.3x resting HR for an hour lands near 50, roughly matching
            # the power-based formula's scale (threshold effort for an hour = 100).
            intensity = (avg_hr - resting_hr) / resting_hr / 0.3
            load = duration_h * intensity**2 * 50
        else:
            continue
        daily_load[d] += load

    ctl_k = 1 - math.exp(-1 / 42)
    atl_k = 1 - math.exp(-1 / 7)
    ctl = atl = 0.0
    series = []
    for d in sorted(daily_load):
        load = daily_load[d]
        ctl += (load - ctl) * ctl_k
        atl += (load - atl) * atl_k
        series.append(
            {
                "date": d,
                "load": round(load, 1),
                "ctl": round(ctl, 1),
                "atl": round(atl, 1),
                "tsb": round(ctl - atl, 1),
            }
        )
    return series


def _training_load_result(series: list[dict]) -> dict[str, Any]:
    latest = series[-1]
    tsb = latest["tsb"]
    if tsb > 5:
        interpretation = (
            "Fresh — fitness is ahead of fatigue, a good window for a hard effort."
        )
    elif tsb < -10:
        interpretation = "Carrying significant fatigue — consider an easy day or rest."
    elif tsb < -5:
        interpretation = "Slightly fatigued — fine for moderate training, maybe not an all-out effort."
    else:
        interpretation = "Fitness and fatigue are roughly balanced."

    return {
        "ctl_fitness": latest["ctl"],
        "atl_fatigue": latest["atl"],
        "tsb_form": tsb,
        "interpretation": interpretation,
        "daily": series[-14:],
    }


def courses_from(g, limit: int = 20) -> list[dict[str, Any]]:
    """Saved Garmin Connect courses from an already-authenticated session."""
    limit = max(1, min(limit, 100))
    raw = g.connectapi("/course-service/course", params={"start": 0, "limit": limit})
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
