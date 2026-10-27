"""Hour-by-hour ride windows, and how ride type changes what counts as rideable."""

import json
from unittest.mock import MagicMock, patch

import garmin_core as gc


def _hour(h, mm=0.0, chance=0, wind=8.0, gust=None, feels=14.0, is_day=True, **extra):
    return {
        "time": f"{h:02d}:00",
        "temp_c": feels,
        "feels_like_c": feels,
        "precipitation_mm": mm,
        "precipitation_chance_pct": chance,
        "wind_mph": wind,
        "gust_mph": gust if gust is not None else wind,
        "is_day": is_day,
        **extra,
    }


# ── rating by ride type ──────────────────────────────────────────────────────


def test_dry_calm_hour_is_good_for_every_ride_type():
    for rt in ("road", "gravel", "mtb"):
        assert gc._rate_hour(_hour(12), rt) == "good"


def test_night_is_poor():
    assert gc._rate_hour(_hour(2, is_day=False), "mtb") == "poor"


def test_light_rain_is_poor_for_road_but_rideable_on_an_mtb():
    h = _hour(12, mm=0.8, chance=70)
    assert gc._rate_hour(h, "road") == "poor"
    assert gc._rate_hour(h, "gravel") == "ok"
    assert gc._rate_hour(h, "mtb") == "ok"


def test_heavy_rain_is_poor_even_on_an_mtb():
    assert gc._rate_hour(_hour(12, mm=3.0, chance=90), "mtb") == "poor"


def test_wind_tolerance_grows_from_road_to_mtb():
    h = _hour(12, wind=27.0)
    assert gc._rate_hour(h, "road") == "poor"
    assert gc._rate_hour(h, "mtb") == "ok"


def test_dry_hour_after_rain_is_a_damp_road():
    h = _hour(12, recent_precip_mm=1.2)
    assert gc._rate_hour(h, "road") == "ok"  # damp, not ideal
    assert gc._rate_hour(h, "gravel") == "ok"
    assert gc._rate_hour(h, "mtb") == "good"  # wet doesn't matter on the trail


def test_unknown_ride_type_means_road():
    h = _hour(12, mm=0.8, chance=70)
    assert gc._rate_hour(h, "unicycle") == gc._rate_hour(h, "road")


# ── windows ──────────────────────────────────────────────────────────────────


def _rated(hours, rt="road"):
    for h in hours:
        h["ride_rating"] = gc._rate_hour(h, rt)
    return hours


def test_wet_morning_dry_afternoon_gives_an_afternoon_window():
    hours = _rated(
        [_hour(h, mm=1.5, chance=90) for h in range(7, 12)]
        + [_hour(h) for h in range(12, 18)]
    )
    (w,) = gc.ride_windows(hours)
    assert (w["start"], w["end"], w["hours"]) == ("12:00", "18:00", 6)
    assert w["total_precip_mm"] == 0


def test_a_poor_hour_splits_the_day_and_the_better_window_wins():
    hours = _rated(
        [_hour(h) for h in (8, 9)]  # 2 good hours
        + [_hour(10, mm=2, chance=90)]  # downpour
        + [_hour(h) for h in range(11, 16)]  # 5 good hours
    )
    windows = gc.ride_windows(hours)
    assert [(w["start"], w["end"]) for w in windows] == [
        ("11:00", "16:00"),
        ("08:00", "10:00"),
    ]


def test_short_perfect_window_beats_long_marginal_one():
    marginal = [_hour(h, chance=40) for h in range(7, 14)]  # 7h of "ok"
    perfect = [_hour(h) for h in range(15, 18)]  # 3h of "good"
    gap = [_hour(14, mm=2, chance=90)]
    windows = gc.ride_windows(_rated(marginal + gap + perfect))
    assert windows[0]["start"] == "15:00"


def test_min_hours_is_respected():
    hours = _rated([_hour(9, mm=2, chance=90), _hour(10), _hour(11, mm=2, chance=90)])
    assert gc.ride_windows(hours, min_hours=2) == []
    assert len(gc.ride_windows(hours, min_hours=1)) == 1


def test_no_dry_daylight_means_no_window():
    hours = _rated(
        [_hour(h, is_day=False) for h in range(0, 6)]  # dry but dark
        + [_hour(h, mm=1, chance=90) for h in range(6, 20)]  # light but wet
    )
    assert gc.ride_windows(hours) == []


# ── end to end through get_weather ───────────────────────────────────────────


def _openmeteo(rain_hours=(), now="2026-01-01T06:30", rain_mm=1.5):
    times = [f"2026-01-01T{h:02d}:00" for h in range(24)]
    rain = [rain_mm if h in rain_hours else 0.0 for h in range(24)]
    payload = {
        "current": {
            "time": now,
            "temperature_2m": 12.0,
            "apparent_temperature": 11.0,
            "precipitation": 0.0,
            "wind_speed_10m": 8.0,
            "wind_direction_10m": 180,
            "weather_code": 1,
            "relative_humidity_2m": 70,
        },
        "daily": {
            "time": ["2026-01-01"],
            "temperature_2m_max": [14.0],
            "temperature_2m_min": [8.0],
            "apparent_temperature_max": [13.0],
            "apparent_temperature_min": [7.0],
            "precipitation_sum": [sum(rain)],
            "wind_speed_10m_max": [12.0],
            "wind_direction_10m_dominant": [180],
            "weather_code": [3],
        },
        "hourly": {
            "time": times,
            "temperature_2m": [12.0] * 24,
            "apparent_temperature": [11.0] * 24,
            "precipitation_probability": [90 if r else 5 for r in rain],
            "wind_speed_10m": [8.0] * 24,
            "weather_code": [3] * 24,
            "precipitation": rain,
            "wind_gusts_10m": [12.0] * 24,
            "is_day": [1 if 7 <= h < 19 else 0 for h in range(24)],
        },
    }
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _weather(**kw):
    ride = {k: kw.pop(k) for k in ("ride_type", "min_ride_hours") if k in kw}
    with patch("urllib.request.urlopen", return_value=_openmeteo(**kw)):
        return gc.get_weather(51.45, -0.97, days=1, **ride)


def test_wet_morning_day_is_rideable_with_an_afternoon_window():
    # 7 mm in the morning: the old whole-day rule (< 2 mm) called this unrideable.
    day = _weather(rain_hours=range(7, 12), now="2026-01-01T06:30")["forecast"][0]
    assert day["precipitation_mm"] > 2
    assert day["rideable"] is True
    # rain ends 11:59; the road stays damp for 3 more hours, so the *good*
    # window starts later, but a (damp) window exists from midday.
    assert day["best_window"]["start"] >= "12:00"
    assert day["best_window"]["end"] == "19:00"


def test_same_wet_day_is_rideable_on_an_mtb_and_not_on_the_road():
    all_day = range(7, 19)
    road = _weather(rain_hours=all_day, rain_mm=1.0)["forecast"][0]
    mtb = _weather(rain_hours=all_day, rain_mm=1.0, ride_type="mtb")["forecast"][0]
    assert road["rideable"] is False
    assert mtb["rideable"] is True


def test_hours_already_gone_today_are_not_offered():
    day = _weather(now="2026-01-01T15:10")["forecast"][0]
    assert day["best_window"]["start"] == "15:00"


def test_hourly_rows_carry_rating_and_damp_flag():
    day = _weather(rain_hours=[9], rain_mm=2.0)["forecast"][0]
    by_time = {h["time"]: h for h in day["hourly"]}
    assert by_time["09:00"]["ride_rating"] == "poor"
    assert by_time["10:00"]["surface_wet"] is True  # just rained
    assert by_time["14:00"]["surface_wet"] is False  # dried out
    assert by_time["14:00"]["ride_rating"] == "good"


def test_result_echoes_ride_type_and_defaults_to_road():
    assert _weather()["ride_type"] == "road"
    assert _weather(ride_type="gravel")["ride_type"] == "gravel"
    assert _weather(ride_type="bogus")["ride_type"] == "road"


def test_min_ride_hours_changes_what_counts():
    # one dry daylight hour between downpours
    rain = [h for h in range(7, 19) if h != 12]
    day1 = _weather(rain_hours=rain, rain_mm=3.0, min_ride_hours=1)["forecast"][0]
    day2 = _weather(rain_hours=rain, rain_mm=3.0, min_ride_hours=2)["forecast"][0]
    assert day1["rideable"] is True
    assert day2["rideable"] is False
