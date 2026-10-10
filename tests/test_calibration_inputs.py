"""Tests for backend.main._gather_calibration_inputs — assembling real
per-day balances and weigh-ins for issue #24's calibration window."""

from datetime import date
from unittest.mock import MagicMock, patch

import backend.main as m


def test_gather_calibration_inputs_skips_unlogged_days():
    g = MagicMock()
    g.get_stats.return_value = {"activeKilocalories": 500}
    g.get_weigh_ins.return_value = {"dailyWeightSummaries": []}
    today = date(2026, 6, 16)

    def fake_food_entries(uid, d):
        # Only one day in the window has food logged.
        if d == "2026-06-15":
            return [{"kcal": 2000, "macros_json": "{}"}]
        return []

    with (
        patch("backend.main.get_food_entries", side_effect=fake_food_entries),
        patch("backend.main.get_manual_activities", return_value=[]),
    ):
        daily_balances, weigh_ins = m._gather_calibration_inputs(
            "uid", g, today, window_days=28
        )

    assert daily_balances == [2000 - 500]
    assert weigh_ins == []


def test_gather_calibration_inputs_collects_weigh_ins_with_offsets():
    g = MagicMock()
    g.get_stats.return_value = {"activeKilocalories": 400}
    g.get_weigh_ins.return_value = {
        "dailyWeightSummaries": [
            {"summaryDate": "2026-05-19", "latestWeight": {"weight": 80000}},
            {"summaryDate": "2026-06-16", "latestWeight": {"weight": 79000}},
        ]
    }
    today = date(2026, 6, 16)

    with (
        patch("backend.main.get_food_entries", return_value=[]),
        patch("backend.main.get_manual_activities", return_value=[]),
    ):
        daily_balances, weigh_ins = m._gather_calibration_inputs(
            "uid", g, today, window_days=28
        )

    assert daily_balances == []
    # window starts 2026-05-19 (today - 28 days) -> offset 0; today -> offset 28,
    # which is out of range [0, window_days) so only the first is kept.
    assert weigh_ins == [(0, 80.0)]


def test_gather_calibration_inputs_handles_garmin_stats_failure():
    g = MagicMock()
    g.get_stats.side_effect = RuntimeError("Garmin unavailable")
    g.get_weigh_ins.return_value = {"dailyWeightSummaries": []}
    today = date(2026, 6, 16)

    with (
        patch(
            "backend.main.get_food_entries",
            return_value=[{"kcal": 2000, "macros_json": "{}"}],
        ),
        patch("backend.main.get_manual_activities", return_value=[]),
    ):
        daily_balances, weigh_ins = m._gather_calibration_inputs(
            "uid", g, today, window_days=5
        )

    assert daily_balances == []
