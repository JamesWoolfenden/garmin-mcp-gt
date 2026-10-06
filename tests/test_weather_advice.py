"""Tests for garmin_mcp._clothing_advice and get_weather's new advice fields."""

import json
from unittest.mock import MagicMock, patch

import garmin_mcp as gm


# ── _clothing_advice ────────────────────────────────────────────────────────


def test_freezing_gets_winter_kit_advice():
    advice = gm._clothing_advice(feels_like_c=-2, wind_mph=5, precipitation_mm=0)
    assert any("winter kit" in a.lower() for a in advice)


def test_cold_gets_thermal_advice():
    advice = gm._clothing_advice(feels_like_c=3, wind_mph=5, precipitation_mm=0)
    assert any("thermal" in a.lower() for a in advice)


def test_warm_gets_shorts_advice():
    advice = gm._clothing_advice(feels_like_c=22, wind_mph=5, precipitation_mm=0)
    assert any("shorts" in a.lower() for a in advice)


def test_very_windy_suggests_indoor():
    advice = gm._clothing_advice(feels_like_c=15, wind_mph=30, precipitation_mm=0)
    assert any("indoor" in a.lower() for a in advice)


def test_moderately_windy_suggests_gilet():
    advice = gm._clothing_advice(feels_like_c=15, wind_mph=18, precipitation_mm=0)
    assert any("windproof" in a.lower() for a in advice)


def test_calm_wind_gives_no_wind_advice():
    advice = gm._clothing_advice(feels_like_c=15, wind_mph=5, precipitation_mm=0)
    assert not any("windproof" in a.lower() or "indoor" in a.lower() for a in advice)


def test_wet_suggests_mudguards():
    advice = gm._clothing_advice(feels_like_c=15, wind_mph=5, precipitation_mm=3)
    assert any("mudguards" in a.lower() for a in advice)


def test_dry_gives_no_wet_advice():
    advice = gm._clothing_advice(feels_like_c=15, wind_mph=5, precipitation_mm=0)
    assert not any("mudguards" in a.lower() for a in advice)


def test_none_values_do_not_crash():
    advice = gm._clothing_advice(
        feels_like_c=None, wind_mph=None, precipitation_mm=None
    )
    assert advice == []


# ── get_weather wiring ──────────────────────────────────────────────────────


def _fake_openmeteo_response():
    payload = {
        "current": {
            "temperature_2m": 12.0,
            "apparent_temperature": 2.0,  # cold feels-like despite mild raw temp
            "precipitation": 0.0,
            "wind_speed_10m": 10.0,
            "wind_direction_10m": 180,
            "weather_code": 1,
            "relative_humidity_2m": 70,
        },
        "daily": {
            "time": ["2026-01-01", "2026-01-02"],
            "temperature_2m_max": [10.0, 18.0],
            "temperature_2m_min": [4.0, 10.0],
            "apparent_temperature_max": [8.0, 16.0],
            "apparent_temperature_min": [0.0, 8.0],
            "precipitation_sum": [5.0, 0.0],
            "wind_speed_10m_max": [30.0, 8.0],
            "wind_direction_10m_dominant": [270, 90],
            "weather_code": [61, 1],
        },
    }
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_get_weather_includes_current_clothing_advice():
    with patch("urllib.request.urlopen", return_value=_fake_openmeteo_response()):
        result = gm.get_weather(51.45, -0.97, days=2)

    current_advice = result["current"]["clothing_advice"]
    assert result["current"]["feels_like_c"] == 2.0
    assert any("thermal" in a.lower() for a in current_advice)


def test_get_weather_forecast_uses_average_feels_like():
    with patch("urllib.request.urlopen", return_value=_fake_openmeteo_response()):
        result = gm.get_weather(51.45, -0.97, days=2)

    day0 = result["forecast"][0]
    # feels_like_max=8.0, feels_like_min=0.0 -> average 4.0 ("cold" tier)
    assert day0["feels_like_max_c"] == 8.0
    assert day0["feels_like_min_c"] == 0.0
    assert any("thermal" in a.lower() for a in day0["clothing_advice"])
    # wet (precipitation_sum=5.0) and windy (30 mph) on day 0
    assert any("mudguards" in a.lower() for a in day0["clothing_advice"])
    assert any("indoor" in a.lower() for a in day0["clothing_advice"])
    assert day0["rideable"] is False

    day1 = result["forecast"][1]
    # feels_like_max=16.0, feels_like_min=8.0 -> average 12.0 ("cool" tier)
    assert any("cool" in a.lower() for a in day1["clothing_advice"])
    assert day1["rideable"] is True
