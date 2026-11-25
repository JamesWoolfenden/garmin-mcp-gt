"""A dropped HR signal is recorded as 0 and Garmin's own averages count it, so a
ride with a long dropout reports an absurdly low average HR. The averages we
report must only count real readings."""

from datetime import datetime, timedelta

import garmin_core as core

T0 = datetime(2026, 11, 25, 18, 26, 40)


def _rec(sec: int, hr):
    return {"timestamp": T0 + timedelta(seconds=sec), "heart_rate": hr}


def _lap(start_sec: int, elapsed: int, avg_hr=None):
    return {
        "start_time": T0 + timedelta(seconds=start_sec),
        "total_elapsed_time": elapsed,
        "avg_heart_rate": avg_hr,
    }


def test_valid_hr_avg_ignores_zero_and_missing():
    assert core._valid_hr_avg([0, 0, 140, None, 160]) == 150.0


def test_valid_hr_avg_is_none_when_no_signal_at_all():
    assert core._valid_hr_avg([0, 0, None]) is None
    assert core._valid_hr_avg([]) is None


def test_session_average_excludes_dropout_and_reports_coverage():
    # 10 s of signal around 140, then 30 s of dropout (zeros).
    records = [_rec(i, 140) for i in range(10)] + [_rec(i, 0) for i in range(10, 40)]

    hr = core._hr_from_records(records, [])

    assert hr["avg_hr_bpm"] == 140.0
    assert hr["hr_coverage_pct"] == 25


def test_lap_average_uses_only_that_laps_real_readings():
    records = [_rec(i, 130) for i in range(10)] + [
        _rec(i, 0 if i % 2 else 150) for i in range(10, 20)
    ]
    laps = [_lap(0, 10, avg_hr=130), _lap(10, 10, avg_hr=75)]  # Garmin's 75 counts zeros

    hr = core._hr_from_records(records, laps)

    assert hr["lap_avg_hr_bpm"] == [130.0, 150.0]


def test_lap_with_no_signal_reports_none_not_garmins_diluted_value():
    records = [_rec(i, 0) for i in range(10)]

    hr = core._hr_from_records(records, [_lap(0, 10, avg_hr=0)])

    assert hr["lap_avg_hr_bpm"] == [None]


def test_lap_falls_back_to_its_own_field_when_no_records_match():
    hr = core._hr_from_records([], [_lap(0, 10, avg_hr=142)])

    assert hr["lap_avg_hr_bpm"] == [142]
    assert hr["avg_hr_bpm"] is None
    assert hr["hr_coverage_pct"] is None
