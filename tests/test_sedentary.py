"""Tests for _analyse_heart_rates — the pure sedentary analysis function."""

from datetime import datetime, timezone, timedelta
from garmin_mcp import _analyse_heart_rates

DATE = "2026-01-15"
# midnight UTC for 2026-01-15
MIDNIGHT_MS = int(
    datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
)


def ts(hour: float, tz_offset_h: float = 0) -> int:
    """Return a UTC ms timestamp for DATE at the given local hour."""
    return int(MIDNIGHT_MS + (hour - tz_offset_h) * 3600 * 1000)


def make_data(
    readings: list[tuple[int, int]], resting: int = 60, tz_offset_h: float = 0
) -> dict:
    local_midnight = datetime(2026, 1, 15, 0, 0, 0)
    gmt_midnight = datetime(2026, 1, 15, 0, 0, 0) - timedelta(hours=tz_offset_h)
    return {
        "restingHeartRate": resting,
        "heartRateValues": [[t, b] for t, b in readings],
        "startTimestampGMT": gmt_midnight.strftime("%Y-%m-%dT%H:%M:%S"),
        "startTimestampLocal": local_midnight.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def test_empty_data_returns_error():
    result = _analyse_heart_rates({"heartRateValues": []}, DATE)
    assert "error" in result
    assert result["date"] == DATE


def test_none_readings_returns_error():
    result = _analyse_heart_rates({}, DATE)
    assert "error" in result


def test_all_sedentary():
    # resting=60, threshold=80; readings at 65 bpm all day
    readings = [(ts(h + 0.5), 65) for h in range(8)]
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["time_hours"]["sedentary"] > 0
    assert result["time_hours"]["light"] == 0.0
    assert result["time_hours"]["active"] == 0.0


def test_active_reading_classified_correctly():
    # resting=60: sedentary≤80, light≤100, moderate≤120, active>120
    # Use 10 readings per zone at 1-min intervals so buckets round above 0.0
    readings = (
        [(ts(8) + i * 60000, 65) for i in range(10)]  # sedentary
        + [(ts(9) + i * 60000, 85) for i in range(10)]  # light
        + [(ts(10) + i * 60000, 105) for i in range(10)]  # moderate
        + [(ts(11) + i * 60000, 125) for i in range(10)]  # active
    )
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["time_hours"]["sedentary"] > 0
    assert result["time_hours"]["light"] > 0
    assert result["time_hours"]["moderate"] > 0
    assert result["time_hours"]["active"] > 0


def test_cross_midnight_readings_filtered_out():
    # A reading at yesterday 23:00 UTC = yesterday local in UTC+0
    yesterday_ts = int(
        datetime(2026, 1, 14, 23, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    readings = [
        (yesterday_ts, 65),  # should be filtered (wrong date)
        (ts(8), 65),  # today, should be included
        (ts(9), 65),
    ]
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    # Only 2 readings should count, not 3
    assert result["hourly_avg_bpm"].get("23:00") is None


def test_device_off_gap_doesnt_inflate_interval():
    # 60 readings at 1-min intervals, then a 3-hour gap, then more readings
    readings = [(ts(8) + i * 60000, 65) for i in range(60)]
    readings += [(ts(12) + i * 60000, 65) for i in range(10)]  # 3h gap then resume
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    # Total time should not exceed the actual reading count * 1 min
    total_min = sum(result["time_hours"].values()) * 60
    assert total_min <= 75  # 70 readings * 1 min + small tolerance


def test_trailing_sedentary_streak_counted():
    # Sedentary for 30 min then nothing — trailing streak should be counted
    readings = [(ts(8) + i * 60000, 65) for i in range(30)]
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["activity_breaks_count"] == 1


def test_activity_break_counted_on_transition():
    # 30 min sedentary, then active, then sedentary again
    readings = (
        [(ts(8) + i * 60000, 65) for i in range(30)]  # sedentary
        + [(ts(8, 0) + 30 * 60000 + i * 60000, 100) for i in range(5)]  # active
        + [(ts(9) + i * 60000, 65) for i in range(20)]  # sedentary again
    )
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["activity_breaks_count"] >= 1


def test_hourly_avg_bpm_correct():
    # Two readings in hour 9: 60 and 80 → avg 70
    readings = [
        (ts(9) + 0, 60),
        (ts(9) + 30 * 60000, 80),
    ]
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["hourly_avg_bpm"]["09:00"] == 70


def test_timezone_offset_applied():
    # UTC+1: midnight local = 23:00 UTC previous day
    # A reading at UTC 07:00 = local 08:00 should appear in hour 8
    reading_ts = int(
        datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    data = {
        "restingHeartRate": 60,
        "heartRateValues": [[reading_ts, 65]],
        "startTimestampGMT": "2026-01-14T23:00:00",
        "startTimestampLocal": "2026-01-15T00:00:00",
    }
    result = _analyse_heart_rates(data, DATE)
    assert "08:00" in result["hourly_avg_bpm"]


def test_longest_streak_tracked():
    # 45 consecutive sedentary readings at 1 min each
    readings = [(ts(8) + i * 60000, 65) for i in range(45)]
    data = make_data(readings, resting=60)
    result = _analyse_heart_rates(data, DATE)
    assert result["longest_sedentary_streak_min"] == 45
