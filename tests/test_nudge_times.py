"""Tests for per-user nudge_times filtering in /internal/nudge."""

import re
from unittest.mock import patch, AsyncMock

import backend.main as m
from fastapi.testclient import TestClient


def test_current_hour_label_format():
    label = m._current_hour_label("Europe/London")
    assert re.fullmatch(r"\d{2}:00", label)


def test_current_hour_label_invalid_timezone_falls_back():
    # Must not raise, and must still produce a valid "HH:00" label.
    label = m._current_hour_label("Not/A_Real_Zone")
    assert re.fullmatch(r"\d{2}:00", label)


def test_current_hour_label_none_falls_back_to_default():
    label = m._current_hour_label(None)
    assert re.fullmatch(r"\d{2}:00", label)


_balance_stub = {
    "status": "over",
    "recommendation": "eat less",
    "garmin_available": False,
    "kcal_in": 0,
    "kcal_burned": 0,
    "kcal_target": 2000,
    "balance": 0,
    "activity_today": [],
}


def _client():
    return TestClient(m.app, raise_server_exceptions=False)


def test_user_matching_current_hour_gets_pushed():
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["uid1"]),
        patch("backend.main.get_profile", return_value={"nudge_times": ["08:00"], "timezone": "Europe/London"}),
        patch("backend.main._current_hour_label", return_value="08:00"),
        patch("backend.main._compute_balance", new_callable=AsyncMock, return_value=_balance_stub),
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
    mock_send.assert_called_once()


def test_user_not_matching_current_hour_is_skipped():
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["uid1"]),
        patch("backend.main.get_profile", return_value={"nudge_times": ["20:00"], "timezone": "Europe/London"}),
        patch("backend.main._current_hour_label", return_value="08:00"),
        patch("backend.main._compute_balance", new_callable=AsyncMock) as mock_balance,
        patch("backend.main.send_push") as mock_send,
    ):
        resp = _client().post(
            "/internal/nudge", headers={"X-Internal-Secret": "correct-secret"}
        )
    assert resp.json() == {"pushed": 0}
    mock_balance.assert_not_called()  # skipped before the expensive Garmin/Claude fetch
    mock_send.assert_not_called()


def test_mixed_users_only_matching_one_pushed():
    profiles = {
        "match": {"nudge_times": ["08:00"], "timezone": "Europe/London"},
        "nomatch": {"nudge_times": ["20:00"], "timezone": "Europe/London"},
    }
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["match", "nomatch"]),
        patch("backend.main.get_profile", side_effect=lambda uid: profiles[uid]),
        patch("backend.main._current_hour_label", return_value="08:00"),
        patch("backend.main._compute_balance", new_callable=AsyncMock, return_value=_balance_stub),
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
    mock_send.assert_called_once()


def test_empty_nudge_times_never_pushes():
    with (
        patch("backend.main.get_all_subscribed_users", return_value=["uid1"]),
        patch("backend.main.get_profile", return_value={"nudge_times": [], "timezone": "Europe/London"}),
        patch("backend.main._current_hour_label", return_value="08:00"),
        patch("backend.main._compute_balance", new_callable=AsyncMock) as mock_balance,
    ):
        resp = _client().post(
            "/internal/nudge", headers={"X-Internal-Secret": "correct-secret"}
        )
    assert resp.json() == {"pushed": 0}
    mock_balance.assert_not_called()
