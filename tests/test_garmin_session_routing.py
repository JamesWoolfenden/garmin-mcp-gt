"""Regression tests for the per-user Garmin session routing bug.

get_sleep and the weight-trend enrichment used to call into garmin_mcp.py's
module-level client() singleton (authenticated from a local token dir this
container never populates) instead of the caller's per-user GarminSession.
That made the Ask tab's sleep question and weight-trend enrichment fail for
every real user. _compute_sleep and _compute_weight_trend now take the
per-user client directly — these tests prove that, and would fail loudly
again if either code path reverted to going through garmin_mcp.client().
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import backend.main as m


class _FakeSession:
    """Stand-in for GarminSession(uid) that hands back a fixed fake client."""

    def __init__(self, fake_client):
        self._client = fake_client

    def __call__(self, uid):
        return self

    def __enter__(self):
        return self._client

    def __exit__(self, *_exc):
        return False


def _no_global_client():
    """Patch garmin_mcp.client() to blow up if anything still calls it."""
    return patch(
        "garmin_mcp.client",
        side_effect=AssertionError(
            "must not use garmin_mcp's global client() singleton"
        ),
    )


# ── _compute_sleep ──────────────────────────────────────────────────────────


def test_compute_sleep_extracts_fields():
    g = MagicMock()
    g.get_sleep_data.return_value = {
        "dailySleepDTO": {
            "sleepScores": {"overall": {"value": 85}},
            "sleepTimeSeconds": 27000,
            "deepSleepSeconds": 5400,
            "remSleepSeconds": 3600,
            "lightSleepSeconds": 14400,
            "awakeSleepSeconds": 1200,
            "averageSpO2Value": 96,
            "averageRestingHeartRate": 52,
            "averageStressLevel": 22,
        }
    }

    result = m._compute_sleep(g, date.today(), offset_days=0)

    assert result["sleep_score"] == 85
    assert result["total_sleep_h"] == 7.5
    assert result["deep_min"] == 90
    assert result["rem_min"] == 60
    assert result["light_min"] == 240
    assert result["awake_min"] == 20
    assert result["avg_spo2_pct"] == 96
    assert result["avg_resting_hr_bpm"] == 52
    assert result["avg_stress"] == 22
    g.get_sleep_data.assert_called_once_with(date.today().isoformat())


def test_compute_sleep_offset_days_shifts_date():
    g = MagicMock()
    g.get_sleep_data.return_value = {"dailySleepDTO": {}}

    result = m._compute_sleep(g, date.today(), offset_days=2)

    expected = (date.today() - timedelta(days=2)).isoformat()
    assert result["date"] == expected
    g.get_sleep_data.assert_called_once_with(expected)


# ── _compute_weight_trend ───────────────────────────────────────────────────


def test_compute_weight_trend_change_from_prev_week():
    today = date.today()
    this_week_day = today
    last_week_day = today - timedelta(days=7)

    g = MagicMock()
    g.get_weigh_ins.return_value = {
        "dailyWeightSummaries": [
            {
                "summaryDate": this_week_day.isoformat(),
                "latestWeight": {"weight": 70000, "bodyFat": 15.0, "muscleMass": 30000},
            },
            {
                "summaryDate": last_week_day.isoformat(),
                "latestWeight": {"weight": 71000},
            },
        ]
    }

    trend = m._compute_weight_trend(g, today, weeks=2)

    assert len(trend) == 2
    assert trend[0]["avg_weight_kg"] == 71.0  # older week
    assert trend[1]["avg_weight_kg"] == 70.0  # current week
    assert trend[1]["change_from_prev_week_kg"] == -1.0
    assert trend[1]["avg_body_fat_pct"] == 15.0
    assert trend[1]["avg_muscle_mass_kg"] == 30.0


def test_compute_weight_trend_no_data_returns_empty():
    g = MagicMock()
    g.get_weigh_ins.return_value = {"dailyWeightSummaries": []}

    assert m._compute_weight_trend(g, date.today(), weeks=2) == []


# ── _execute_garmin_tool routing ────────────────────────────────────────────


def test_execute_garmin_tool_get_sleep_uses_per_user_session():
    fake_client = MagicMock()
    fake_client.get_sleep_data.return_value = {
        "dailySleepDTO": {"sleepScores": {"overall": {"value": 77}}}
    }

    with _no_global_client():
        result = m._execute_garmin_tool(
            "get_sleep", {"offset_days": 0}, "uid123", fake_client
        )

    assert result["sleep_score"] == 77
    fake_client.get_sleep_data.assert_called_once()


def test_execute_garmin_tool_get_weight_trend_uses_per_user_session():
    fake_client = MagicMock()
    fake_client.get_weigh_ins.return_value = {"dailyWeightSummaries": []}

    with _no_global_client():
        result = m._execute_garmin_tool(
            "get_weight_trend", {"weeks": 2}, "uid123", fake_client
        )

    assert result == []
    fake_client.get_weigh_ins.assert_called_once()


# ── _garmin_wellness weight-trend enrichment ────────────────────────────────


def test_garmin_wellness_weight_trend_uses_per_user_session():
    today = date.today()
    fake_client = MagicMock()
    fake_client.get_sleep_data.return_value = {"dailySleepDTO": {}}
    fake_client.get_hrv_data.return_value = {}
    fake_client.get_cycling_ftp.return_value = {}
    fake_client.get_weigh_ins.return_value = {
        "dailyWeightSummaries": [
            {"summaryDate": today.isoformat(), "latestWeight": {"weight": 70000}},
            {
                "summaryDate": (today - timedelta(days=7)).isoformat(),
                "latestWeight": {"weight": 71000},
            },
        ]
    }

    with (
        patch("backend.main.GarminSession", _FakeSession(fake_client)),
        _no_global_client(),
    ):
        result = m._garmin_wellness("uid123")

    assert result["weight_trend_7d_kg"] == -1.0
    assert result["weight_kg"] == 70.0


# ── /chat reuses one Garmin session across tool calls ───────────────────────


class _CountingSession:
    """Stand-in for GarminSession(uid) that counts how many times a session
    is opened/closed, to prove /chat reuses one session across every tool
    call in a turn instead of logging in again (with a fresh KMS decrypt +
    Garmin login + re-encrypt) for each one."""

    opens = 0
    exits = 0

    def __init__(self, uid):
        pass

    def __enter__(self):
        _CountingSession.opens += 1
        fake_client = MagicMock()
        fake_client.get_stats.return_value = {}
        fake_client.get_heart_rates.return_value = {}
        fake_client.get_body_battery.return_value = []
        fake_client.get_sleep_data.return_value = {"dailySleepDTO": {}}
        return fake_client

    def __exit__(self, *_exc):
        _CountingSession.exits += 1
        return False


def _tool_use_block(name, tool_input, call_id):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = tool_input
    block.id = call_id
    return block


def test_chat_reuses_one_garmin_session_across_tool_calls():
    _CountingSession.opens = 0
    _CountingSession.exits = 0

    tool_use_response = MagicMock()
    tool_use_response.stop_reason = "tool_use"
    tool_use_response.content = [
        _tool_use_block("get_today_stats", {}, "call_1"),
        _tool_use_block("get_sleep", {"offset_days": 0}, "call_2"),
    ]

    end_response = MagicMock()
    end_response.stop_reason = "end_turn"
    end_response.content = [MagicMock(text="All done")]

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.side_effect = [tool_use_response, end_response]

    with (
        patch("backend.main.ANTHROPIC_CLIENT", mock_anthropic),
        patch("backend.main.GarminSession", _CountingSession),
    ):
        result = asyncio.run(
            m.chat(m.ChatRequest(message="how am I doing today?"), "uid123")
        )

    assert result == {"response": "All done"}
    # Two Garmin tool calls in the same turn should open exactly one
    # session, not one per call.
    assert _CountingSession.opens == 1
    assert _CountingSession.exits == 1
