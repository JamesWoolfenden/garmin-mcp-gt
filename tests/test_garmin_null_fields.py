"""Regression test for a production crash: Garmin returns an explicit null
(not a missing key) for daily-stats fields on a day that's only just
started (e.g. moments after local midnight in the user's timezone — more
reachable now that #23 uses the user's own local day instead of server
UTC). `.get(key, 0)` only substitutes 0 for a MISSING key, not for a
present key whose value is None, so `_garmin_today` crashed building the
synthetic 'N steps' activity: `f"{None:,} steps"` -> TypeError.
"""

from unittest.mock import patch

from tests.test_garmin_session_routing import _FakeSession, _no_global_client

import backend.main as m


def _stats_with_nulls():
    # What Garmin's API actually returns a few minutes after local midnight:
    # the keys are present, but every not-yet-accumulated field is null.
    return {
        "activeKilocalories": None,
        "totalKilocalories": None,
        "totalSteps": None,
        "totalDistanceMeters": None,
        "activeSeconds": None,
        "bodyBatteryMostRecentValue": None,
    }


def test_garmin_today_survives_null_stats_fields():
    fake_client = type("_C", (), {})()
    fake_client.get_stats = lambda d: _stats_with_nulls()
    fake_client.get_heart_rates = lambda d: {"restingHeartRate": None}
    fake_client.get_body_battery = lambda d: []

    with (
        patch("backend.main.GarminSession", _FakeSession(fake_client)),
        patch("backend.main.get_profile", return_value={"timezone": "Europe/London"}),
        _no_global_client(),
    ):
        result = m._garmin_today("uid123")

    assert result is not None
    assert result["active_kcal"] == 0
    assert result["total_kcal"] == 0
    assert result["steps"] == 0
    assert result["distance_km"] == 0
    assert result["active_minutes"] == 0
    # Must not include a 'current' battery reading built from a None value.
    assert "current" not in result["body_battery"]


def test_compute_sleep_survives_null_fields():
    from datetime import date

    fake_client = type("_C", (), {})()
    fake_client.get_sleep_data = lambda d: {
        "dailySleepDTO": {
            "sleepScores": {"overall": {}},
            "sleepTimeSeconds": None,
            "deepSleepSeconds": None,
            "remSleepSeconds": None,
            "lightSleepSeconds": None,
            "awakeSleepSeconds": None,
        }
    }

    result = m._compute_sleep(fake_client, date(2026, 6, 16), offset_days=0)

    assert result["total_sleep_h"] == 0
    assert result["deep_min"] == 0
    assert result["rem_min"] == 0
    assert result["light_min"] == 0
    assert result["awake_min"] == 0
