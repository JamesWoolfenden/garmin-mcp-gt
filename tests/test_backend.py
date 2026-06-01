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
            '{"parsed": "bowl of porridge", "kcal": 350}'
        )
        result = m.claude_parse_food("porridge")
        assert result["kcal"] == 350
        assert result["parsed"] == "bowl of porridge"

    def test_markdown_wrapped_json(self):
        self.mock_client.messages.create.return_value = _make_message(
            '```json\n{"parsed": "banana", "kcal": 90}\n```'
        )
        result = m.claude_parse_food("banana")
        assert result["kcal"] == 90

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

    def test_morning_includes_activity_guidance(self):
        prompt = self._get_system_prompt("08:00")
        assert "plenty of time" in prompt

    def test_afternoon_includes_limited_guidance(self):
        prompt = self._get_system_prompt("14:00")
        assert "still time" in prompt

    def test_evening_drops_activity_guidance(self):
        prompt = self._get_system_prompt("19:00")
        assert "too late" in prompt
