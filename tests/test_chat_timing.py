"""/chat logs one timing line per turn (Hosting cuts proxied requests at 60s)."""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import backend.main as m


def _msg(stop_reason, content):
    r = MagicMock()
    r.stop_reason = stop_reason
    r.content = content
    return r


def _text(t):
    b = MagicMock(spec=["text", "type"])
    b.text = t
    b.type = "text"
    return b


@pytest.fixture
def chat(monkeypatch):
    m.app.dependency_overrides[m.current_user] = lambda: "u1"
    monkeypatch.setattr(m, "today_str", lambda uid: "2026-10-27")
    monkeypatch.setattr(m, "save_chat_message", lambda *a, **k: None)
    yield TestClient(m.app, raise_server_exceptions=False)
    m.app.dependency_overrides.clear()


def _timing_records(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("chat turn")]


def test_logs_ok_turn_at_info(chat, monkeypatch, caplog):
    client = MagicMock()
    client.messages.create.return_value = _msg("end_turn", [_text("hi")])
    monkeypatch.setattr(m, "ANTHROPIC_CLIENT", client)
    with caplog.at_level(logging.INFO, logger=m.logger.name):
        resp = chat.post("/chat", json={"message": "hello"})
    assert resp.json() == {"response": "hi"}
    (rec,) = _timing_records(caplog)
    assert rec.levelno == logging.INFO
    assert "outcome=ok rounds=1 tools=-" in rec.getMessage()


def test_slow_turn_is_a_warning_and_lists_tools(chat, monkeypatch, caplog):
    tool = MagicMock()
    tool.type = "tool_use"
    tool.name = "get_food_log"
    tool.id = "t1"
    tool.input = {}
    client = MagicMock()
    client.messages.create.side_effect = [
        _msg("tool_use", [tool]),
        _msg("end_turn", [_text("done")]),
    ]
    monkeypatch.setattr(m, "ANTHROPIC_CLIENT", client)
    monkeypatch.setattr(m, "_execute_garmin_tool", lambda *a, **k: {"entries": []})
    monkeypatch.setattr(m, "_CHAT_SLOW_S", 0)  # any elapsed time counts as slow
    with caplog.at_level(logging.INFO, logger=m.logger.name):
        resp = chat.post("/chat", json={"message": "what did I eat"})
    assert resp.json() == {"response": "done"}
    (rec,) = _timing_records(caplog)
    assert rec.levelno == logging.WARNING
    assert "outcome=ok rounds=2 tools=get_food_log" in rec.getMessage()


def test_failed_turn_is_still_logged_as_error_outcome(chat, monkeypatch, caplog):
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("anthropic down")
    monkeypatch.setattr(m, "ANTHROPIC_CLIENT", client)
    with caplog.at_level(logging.INFO, logger=m.logger.name):
        resp = chat.post("/chat", json={"message": "hello"})
    assert resp.status_code == 500
    (rec,) = _timing_records(caplog)
    assert "outcome=error" in rec.getMessage()
