"""goal_context turns the profile's training goal into a prompt line."""

from datetime import date

import backend.main as m

GOAL = {
    "goal_name": "Example Tour",
    "goal_date": "2027-05-02",
    "goal_details": "1,000 km, 10,000 m",
}


def test_no_goal_returns_none():
    assert m.goal_context({}, date(2026, 10, 30)) is None
    assert (
        m.goal_context({"goal_name": "x", "goal_date": ""}, date(2026, 10, 30)) is None
    )


def test_bad_date_returns_none():
    assert (
        m.goal_context({**GOAL, "goal_date": "2027-13-45"}, date(2026, 10, 30)) is None
    )


def test_past_goal_returns_none():
    assert m.goal_context(GOAL, date(2027, 6, 1)) is None


def test_weeks_and_details_in_text():
    text = m.goal_context(GOAL, date(2026, 10, 30))
    assert "Example Tour" in text
    assert "26 weeks to go" in text
    assert "1,000 km" in text


def test_phase_boundaries():
    cases = {
        date(2026, 10, 30): "base phase",
        date(2027, 1, 1): "build phase",
        date(2027, 3, 25): "peak phase",
        date(2027, 4, 20): "taper",
    }
    for today, phase in cases.items():
        assert phase in m.goal_context(GOAL, today), today
