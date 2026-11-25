"""get_weekly_trends summarises cycling per week; Zwift rides (Garmin typeKey
"virtual_ride") must count alongside outdoor rides."""

from datetime import date

import garmin_mcp as gm


class _FakeClient:
    def __init__(self, acts):
        self._acts = acts

    def get_activities_by_date(self, start, end):
        return self._acts


def _act(type_key, start, distance_m, duration_s, power=None):
    return {
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start,
        "distance": distance_m,
        "duration": duration_s,
        "avgPower": power,
    }


def test_virtual_ride_counts_in_weekly_totals(monkeypatch):
    today = date.today().isoformat()
    acts = [
        _act("road_biking", f"{today}T07:00:00", 30000, 3600, power=200),
        _act("virtual_ride", f"{today}T18:00:00", 10000, 1800, power=150),
        _act("open_water_swimming", f"{today}T12:00:00", 1000, 1800),
    ]
    monkeypatch.setattr(gm, "client", lambda: _FakeClient(acts))

    this_week = gm.get_weekly_trends(weeks=1)[-1]

    assert this_week["ride_count"] == 2
    assert this_week["total_km"] == 40.0
    assert this_week["total_hours"] == 1.5
    assert this_week["avg_power_w"] == 175.0


def test_backend_weekly_trends_uses_session_client_and_counts_zwift():
    import backend.main as bm

    today = date.today()
    acts = [
        _act("virtual_ride", f"{today.isoformat()}T18:00:00", 10000, 1800, power=150),
    ]

    result = bm._compute_weekly_trends(_FakeClient(acts), today, weeks=2)

    assert len(result) == 2  # oldest week first, this week last
    assert result[-1]["ride_count"] == 1
    assert result[-1]["total_km"] == 10.0


def test_backend_weekly_trends_clamps_weeks():
    import backend.main as bm

    result = bm._compute_weekly_trends(_FakeClient([]), date.today(), weeks=999)

    assert len(result) == 52
