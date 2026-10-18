"""_compute_vo2max used to call Garmin's get_max_metrics once per day in a
plain sequential loop — a 90-day /progression request meant 90 sequential
HTTP round trips, the single biggest contributor to that endpoint's latency.
It now fires those calls concurrently via a bounded ThreadPoolExecutor.
These tests prove the concurrent version still returns results in the same
oldest-to-newest order and still tolerates individual days failing.
"""

from datetime import date, timedelta

import backend.main as m


def test_vo2max_results_are_oldest_to_newest_despite_concurrency():
    today = date.today()

    def fake_get_max_metrics(d: str):
        return [{"generic": {"vo2MaxValue": 40 + int(d[-2:])}}]

    g = type("FakeClient", (), {"get_max_metrics": staticmethod(fake_get_max_metrics)})()

    results = m._compute_vo2max(g, today, days=5)

    expected_dates = [(today - timedelta(days=i)).isoformat() for i in range(4, -1, -1)]
    assert [r["date"] for r in results] == expected_dates


def test_vo2max_tolerates_individual_day_failures():
    today = date.today()
    failing_date = (today - timedelta(days=2)).isoformat()

    def fake_get_max_metrics(d: str):
        if d == failing_date:
            raise RuntimeError("Garmin API hiccup for this one day")
        return [{"generic": {"vo2MaxValue": 42}}]

    g = type("FakeClient", (), {"get_max_metrics": staticmethod(fake_get_max_metrics)})()

    results = m._compute_vo2max(g, today, days=5)

    assert len(results) == 4
    assert failing_date not in [r["date"] for r in results]


def test_vo2max_skips_days_with_no_qualifying_metric():
    today = date.today()

    def fake_get_max_metrics(d: str):
        return [{"generic": {}}]  # no vo2MaxValue, no lactateThresholdHeartRate

    g = type("FakeClient", (), {"get_max_metrics": staticmethod(fake_get_max_metrics)})()

    assert m._compute_vo2max(g, today, days=5) == []
