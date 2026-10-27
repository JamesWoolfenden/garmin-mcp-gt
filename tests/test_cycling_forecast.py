"""/cycling-forecast: ride type and window length pass through; days and the
"best times" list are ranked by their best ride window, not whole-day totals."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import backend.main as m


def _win(start, end, score, mm=0.0, wind=8.0):
    return {
        "start": start,
        "end": end,
        "hours": int(end[:2]) - int(start[:2]),
        "good_hours": 1,
        "score": score,
        "total_precip_mm": mm,
        "max_wind_mph": wind,
        "avg_temp_c": 12.0,
        "max_precip_chance_pct": 5,
    }


def _day(date, windows, mm=0.0, wind=10.0):
    return {
        "date": date,
        "rideable": bool(windows),
        "ride_windows": windows,
        "best_window": windows[0] if windows else None,
        "precipitation_mm": mm,
        "max_wind_mph": wind,
    }


@pytest.fixture
def forecast(monkeypatch):
    m.app.dependency_overrides[m.current_user] = lambda: "u1"
    monkeypatch.setattr(
        m, "get_profile", lambda uid: {"latitude": 51.4, "longitude": -1}
    )
    monkeypatch.setattr(m, "today_str", lambda uid: "2026-01-01")

    async def no_garmin(uid):
        return None, [], {}

    monkeypatch.setattr(m, "_fetch_garmin_data", no_garmin)
    get_weather = MagicMock()
    monkeypatch.setattr("garmin_core.get_weather", get_weather)
    yield TestClient(m.app, raise_server_exceptions=False), get_weather
    m.app.dependency_overrides.clear()


def test_options_pass_through_and_are_echoed(forecast):
    client, get_weather = forecast
    get_weather.return_value = {"forecast": []}
    r = client.get("/cycling-forecast?ride_type=mtb&min_hours=3")
    body = r.json()
    assert (body["ride_type"], body["min_hours"]) == ("mtb", 3)
    assert get_weather.call_args.args[3:] == (3, "mtb")


def test_defaults_are_road_and_two_hours(forecast):
    client, get_weather = forecast
    get_weather.return_value = {"forecast": []}
    body = client.get("/cycling-forecast").json()
    assert (body["ride_type"], body["min_hours"]) == ("road", 2)


def test_min_hours_is_clamped(forecast):
    client, get_weather = forecast
    get_weather.return_value = {"forecast": []}
    assert client.get("/cycling-forecast?min_hours=99").json()["min_hours"] == 6
    assert client.get("/cycling-forecast?min_hours=-4").json()["min_hours"] == 1


def test_unknown_ride_type_is_rejected(forecast):
    client, _ = forecast
    assert client.get("/cycling-forecast?ride_type=tank").status_code == 400


def test_best_days_follow_the_best_window_not_whole_day_totals(forecast):
    client, get_weather = forecast
    get_weather.return_value = {
        "forecast": [
            # breezy but with a long, excellent window
            _day("2026-01-01", [_win("10:00", "16:00", 6.0)], mm=0.0, wind=20),
            # calm and dry all day but only a marginal window
            _day("2026-01-02", [_win("12:00", "14:00", 1.2)], mm=0.0, wind=2),
            _day("2026-01-03", []),  # nothing rideable
            _day("2026-01-04", [_win("09:00", "12:00", 3.0)], mm=3.0, wind=15),
        ]
    }
    body = client.get("/cycling-forecast").json()
    assert body["best_dates"] == ["2026-01-01", "2026-01-04", "2026-01-02"]


def test_best_windows_lists_top_three_across_days(forecast):
    client, get_weather = forecast
    get_weather.return_value = {
        "forecast": [
            _day(
                "2026-01-01", [_win("10:00", "16:00", 6.0), _win("07:00", "09:00", 2.0)]
            ),
            _day("2026-01-02", [_win("12:00", "15:00", 3.0)]),
            _day("2026-01-03", [_win("09:00", "11:00", 4.5)]),
        ]
    }
    got = client.get("/cycling-forecast").json()["best_windows"]
    assert [(w["date"], w["start"]) for w in got] == [
        ("2026-01-01", "10:00"),
        ("2026-01-03", "09:00"),
        ("2026-01-02", "12:00"),
    ]
