"""Tests for backend/main.py — Claude parsing and nudge auth."""

import json
import pytest
from unittest.mock import MagicMock, patch

import backend.main as m
from fastapi.testclient import TestClient


def _make_message(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


# ── claude_parse_food ─────────────────────────────────────────────────────────


class TestClaudeParseFood:
    def setup_method(self):
        self.mock_client = MagicMock()
        m.ANTHROPIC_CLIENT = self.mock_client

    def test_clean_json(self):
        self.mock_client.messages.create.return_value = _make_message(
            '{"parsed": "bowl of porridge", "kcal": 350, "carbs_g": 60, "protein_g": 10, "fat_g": 5}'
        )
        result = m.claude_parse_food("porridge")
        assert result["kcal"] == 350
        assert result["parsed"] == "bowl of porridge"
        assert result["carbs_g"] == 60

    def test_markdown_wrapped_json(self):
        self.mock_client.messages.create.return_value = _make_message(
            '```json\n{"parsed": "banana", "kcal": 90, "carbs_g": 23, "protein_g": 1, "fat_g": 0}\n```'
        )
        result = m.claude_parse_food("banana")
        assert result["kcal"] == 90
        assert result["carbs_g"] == 23

    def test_invalid_json_raises(self):
        self.mock_client.messages.create.return_value = _make_message(
            "Sorry, I cannot estimate that."
        )
        with pytest.raises(json.JSONDecodeError):
            m.claude_parse_food("??")


# ── nudge auth ────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(m.app, raise_server_exceptions=False)


def test_wrong_secret_returns_401(client):
    resp = client.post("/internal/nudge", headers={"X-Internal-Secret": "wrong"})
    assert resp.status_code == 401


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


def test_correct_secret_passes_auth(client):
    with (
        patch("backend.main.get_all_subscribed_users", return_value=[]),
        patch("backend.main._compute_balance", return_value=_balance_stub),
    ):
        resp = client.post(
            "/internal/nudge", headers={"X-Internal-Secret": "correct-secret"}
        )
    assert resp.status_code != 401


def test_no_internal_secret_allows_all(client):
    original = m.INTERNAL_SECRET
    m.INTERNAL_SECRET = ""
    try:
        with (
            patch("backend.main.get_all_subscribed_users", return_value=[]),
            patch("backend.main._compute_balance", return_value=_balance_stub),
        ):
            resp = client.post("/internal/nudge")
        assert resp.status_code != 401
    finally:
        m.INTERNAL_SECRET = original


# ── health ────────────────────────────────────────────────────────────────────


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── nudge timing ──────────────────────────────────────────────────────────────


class TestNudgeTiming:
    def setup_method(self):
        self.mock_client = MagicMock()
        m.ANTHROPIC_CLIENT = self.mock_client
        self.mock_client.messages.create.return_value = _make_message(
            '{"status": "under", "recommendation": "Go for a walk."}'
        )

    def _get_system_prompt(self, time_of_day: str) -> str:
        m.claude_recommend(0, 0, 2000, [], time_of_day)
        call_args = self.mock_client.messages.create.call_args
        return call_args.kwargs.get(
            "system", call_args.args[0] if call_args.args else ""
        )

    def test_time_in_prompt(self):
        assert "08:00" in self._get_system_prompt("08:00")

    def test_workout_in_prompt(self):
        m.claude_recommend(
            0,
            0,
            2000,
            [
                {
                    "name": "Morning ride",
                    "type": "road_biking",
                    "duration_min": 60,
                    "avg_power_w": 200,
                    "kcal": 600,
                }
            ],
            "14:00",
        )
        prompt = self.mock_client.messages.create.call_args.kwargs.get("system", "")
        assert "Morning ride" in prompt
        assert "200W" in prompt

    def test_body_battery_in_prompt(self):
        m.claude_recommend(0, 0, 2000, [], "08:00", {"body_battery_charged": 45})
        prompt = self.mock_client.messages.create.call_args.kwargs.get("system", "")
        assert "Body battery: 45%" in prompt

    def test_hrv_in_prompt(self):
        m.claude_recommend(0, 0, 2000, [], "08:00", {"hrv_last_night": 58})
        prompt = self.mock_client.messages.create.call_args.kwargs.get("system", "")
        assert "HRV: 58ms" in prompt

    def test_weight_trend_in_prompt(self):
        m.claude_recommend(0, 0, 2000, [], "08:00", {"weight_trend_7d_kg": -0.3})
        prompt = self.mock_client.messages.create.call_args.kwargs.get("system", "")
        assert "trending down" in prompt
