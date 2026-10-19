"""get_training_load estimates a Performance Management Chart (CTL/ATL/TSB) from
activity duration and intensity, without downloading every ride's FIT file. These
tests cover the pure PMC math in garmin_mcp and the per-user wrapper in backend.main.
"""

from datetime import date, timedelta

import backend.main as m
import garmin_mcp as gm


def _ride(days_ago: int, duration_s: int, avg_power=None, avg_hr=None, type_key="road_biking"):
    d = date.today() - timedelta(days=days_ago)
    return {
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{d.isoformat()}T07:00:00",
        "duration": duration_s,
        "avgPower": avg_power,
        "averageHR": avg_hr,
    }


def test_rest_period_has_zero_load_and_balanced_form():
    today = date.today()
    series = gm._training_load_series([], today, days=14, ftp=250, resting_hr=50)
    result = gm._training_load_result(series)

    assert result["ctl_fitness"] == 0
    assert result["atl_fatigue"] == 0
    assert result["tsb_form"] == 0
    assert "balanced" in result["interpretation"].lower()


def test_hard_week_at_ftp_pushes_form_negative():
    today = date.today()
    # Four 1-hour rides at FTP in the last week (TSS ~100 each) — fatigue should
    # build faster than fitness (ATL has a 7-day time constant vs CTL's 42-day).
    acts = [_ride(days_ago=i, duration_s=3600, avg_power=250) for i in (1, 2, 4, 6)]

    series = gm._training_load_series(acts, today, days=42, ftp=250, resting_hr=50)
    result = gm._training_load_result(series)

    assert result["atl_fatigue"] > result["ctl_fitness"]
    assert result["tsb_form"] < 0
    assert "fatigue" in result["interpretation"].lower() or "easy" in result["interpretation"].lower()


def test_non_cycling_running_activities_are_ignored():
    today = date.today()
    acts = [_ride(days_ago=1, duration_s=3600, avg_power=250, type_key="open_water_swimming")]

    series = gm._training_load_series(acts, today, days=14, ftp=250, resting_hr=50)

    assert all(day["load"] == 0 for day in series)


def test_hr_fallback_used_when_no_power_data():
    today = date.today()
    acts = [_ride(days_ago=1, duration_s=3600, avg_power=None, avg_hr=140)]

    series = gm._training_load_series(acts, today, days=14, ftp=250, resting_hr=50)

    loaded_day = next(day for day in series if day["load"] > 0)
    assert loaded_day["load"] > 0


def test_activities_with_neither_power_nor_hr_contribute_no_load():
    today = date.today()
    acts = [_ride(days_ago=1, duration_s=3600)]

    series = gm._training_load_series(acts, today, days=14, ftp=250, resting_hr=50)

    assert all(day["load"] == 0 for day in series)


def test_compute_training_load_uses_per_user_client_and_clamps_days():
    today = date.today()
    captured = {}

    def fake_get_activities_by_date(start, end):
        captured["start"] = start
        captured["end"] = end
        return [_ride(days_ago=1, duration_s=3600, avg_power=200)]

    g = type(
        "FakeClient",
        (),
        {
            "get_activities_by_date": staticmethod(fake_get_activities_by_date),
            "get_cycling_ftp": staticmethod(lambda: {"functionalThresholdPower": 250}),
            "get_stats": staticmethod(lambda d: {"restingHeartRate": 50}),
        },
    )()

    # days=999 should clamp to the max (180), not blow up the window.
    result = m._compute_training_load(g, today, days=999)

    assert captured["start"] == (today - timedelta(days=179)).isoformat()
    assert captured["end"] == today.isoformat()
    assert "tsb_form" in result
