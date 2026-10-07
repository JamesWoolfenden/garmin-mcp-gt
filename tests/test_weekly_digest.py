"""Tests for the weekly digest branch of /internal/nudge."""

from datetime import datetime
from unittest.mock import patch, AsyncMock

import backend.main as m
from fastapi.testclient import TestClient


def _sunday_at(hour: int) -> datetime:
    # 2026-10-11 is a Sunday.
    return datetime(2026, 10, 11, hour, 0)


def _monday_at(hour: int) -> datetime:
    # 2026-10-12 is a Monday.
    return datetime(2026, 10, 12, hour, 0)


# ── _is_weekly_digest_time ──────────────────────────────────────────────────


def test_sunday_at_latest_nudge_time_is_digest_time():
    with patch("backend.main.datetime") as mock_dt:
        mock_dt.now.return_value = _sunday_at(20)
        assert m._is_weekly_digest_time("Europe/London", ["08:00", "20:00"]) is True


def test_sunday_at_earlier_nudge_time_is_not_digest_time():
    with patch("backend.main.datetime") as mock_dt:
        mock_dt.now.return_value = _sunday_at(8)
        assert m._is_weekly_digest_time("Europe/London", ["08:00", "20:00"]) is False


def test_monday_at_latest_nudge_time_is_not_digest_time():
    with patch("backend.main.datetime") as mock_dt:
        mock_dt.now.return_value = _monday_at(20)
        assert m._is_weekly_digest_time("Europe/London", ["08:00", "20:00"]) is False


def test_empty_nudge_times_is_never_digest_time():
    with patch("backend.main.datetime") as mock_dt:
        mock_dt.now.return_value = _sunday_at(20)
        assert m._is_weekly_digest_time("Europe/London", []) is False


def test_single_nudge_time_on_sunday_is_digest_time():
    with patch("backend.main.datetime") as mock_dt:
        mock_dt.now.return_value = _sunday_at(13)
        assert m._is_weekly_digest_time("Europe/London", ["13:00"]) is True


# ── _format_weekly_digest ───────────────────────────────────────────────────


def test_format_weekly_digest_includes_core_stats():
    title, body = m._format_weekly_digest(
        {
            "distance_km": 42.5,
            "activity_kcal": 1800,
            "kcal_in_total": 14000,
            "avg_net_kcal": 300,
            "num_activities": 3,
        }
    )
    assert "42.5km" in title
    assert "3 activities" in body
    assert "1800 kcal burned" in body
    assert "300 kcal/day" in body


def test_format_weekly_digest_mentions_weight_change_when_present():
    _, body = m._format_weekly_digest(
        {
            "distance_km": 10,
            "activity_kcal": 500,
            "kcal_in_total": 7000,
            "avg_net_kcal": 100,
            "num_activities": 1,
            "weight_change_kg": -0.4,
            "weight_kg": 74.6,
        }
    )
    assert "down 0.4kg" in body


def test_format_weekly_digest_omits_weight_when_absent():
    _, body = m._format_weekly_digest(
        {
            "distance_km": 10,
            "activity_kcal": 500,
            "kcal_in_total": 7000,
            "avg_net_kcal": 100,
            "num_activities": 1,
        }
    )
    assert "kg this week" not in body


# ── /internal/nudge integration ─────────────────────────────────────────────

_digest_summary = {
    "distance_km": 20.0,
    "activity_kcal": 900,
    "kcal_in_total": 10000,
    "avg_net_kcal": 150,
    "num_activities": 2,
}


def _client():
    return TestClient(m.app, raise_server_exceptions=False)


def test_nudge_sends_digest_instead_of_daily_balance_on_digest_time():
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["uid1"]),
        patch(
            "backend.main.get_profile",
            return_value={"nudge_times": ["20:00"], "timezone": "Europe/London"},
        ),
        patch("backend.main._current_hour_label", return_value="20:00"),
        patch("backend.main._is_weekly_digest_time", return_value=True),
        patch(
            "backend.main._compute_weekly_summary", return_value=_digest_summary
        ),
        patch("backend.main._compute_balance", new_callable=AsyncMock) as mock_balance,
        patch(
            "backend.main.get_push_subscriptions",
            return_value=[{"endpoint": "https://example.com", "keys": {}}],
        ),
        patch("backend.main.send_push", return_value=True) as mock_send,
    ):
        resp = _client().post(
            "/internal/nudge", headers={"X-Internal-Secret": "correct-secret"}
        )
    assert resp.json() == {"pushed": 1}
    mock_balance.assert_not_called()  # digest branch, not the daily balance path
    title, body = mock_send.call_args.args[1], mock_send.call_args.args[2]
    assert "your week" in title
    assert "2 activities" in body


def test_nudge_skips_user_when_digest_fetch_fails():
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["uid1"]),
        patch(
            "backend.main.get_profile",
            return_value={"nudge_times": ["20:00"], "timezone": "Europe/London"},
        ),
        patch("backend.main._current_hour_label", return_value="20:00"),
        patch("backend.main._is_weekly_digest_time", return_value=True),
        patch("backend.main._compute_weekly_summary", return_value=None),
        patch("backend.main.send_push") as mock_send,
    ):
        resp = _client().post(
            "/internal/nudge", headers={"X-Internal-Secret": "correct-secret"}
        )
    assert resp.json() == {"pushed": 0}
    mock_send.assert_not_called()
