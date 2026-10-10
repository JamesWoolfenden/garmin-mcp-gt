"""Tests for issue #23 — day boundaries and "now" must use the user's own
timezone (profile.timezone), not server UTC. Cloud Run runs in UTC, so
date.today()/datetime.now() put post-midnight-local activity on the wrong
day, and made recommendation time-of-day an hour out during BST."""

import asyncio
from datetime import datetime as real_datetime, timezone as real_timezone
from unittest.mock import AsyncMock, patch

import backend.main as m


class _FixedDatetime(real_datetime):
    """Stand-in for backend.main.datetime with a frozen 'now'."""

    _fixed_utc = real_datetime(2026, 1, 1, tzinfo=real_timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed_utc.astimezone(tz)
        return cls._fixed_utc.replace(tzinfo=None)


def _frozen_at(utc_dt: real_datetime):
    frozen = type("_Frozen", (_FixedDatetime,), {"_fixed_utc": utc_dt.replace(tzinfo=real_timezone.utc)})
    return patch("backend.main.datetime", frozen)


# ── user_today / user_now ────────────────────────────────────────────────────


def test_user_today_uses_local_date_during_bst_not_utc():
    # 2026-06-15 23:30 UTC == 2026-06-16 00:30 in Europe/London (BST, UTC+1).
    with (
        patch("backend.main.get_profile", return_value={"timezone": "Europe/London"}),
        _frozen_at(real_datetime(2026, 6, 15, 23, 30)),
    ):
        assert m.user_today("uid").isoformat() == "2026-06-16"


def test_user_today_handles_negative_utc_offset():
    # 2026-01-10 04:00 UTC == 2026-01-09 20:00 in America/Los_Angeles (UTC-8).
    with (
        patch(
            "backend.main.get_profile",
            return_value={"timezone": "America/Los_Angeles"},
        ),
        _frozen_at(real_datetime(2026, 1, 10, 4, 0)),
    ):
        assert m.user_today("uid").isoformat() == "2026-01-09"


def test_user_today_falls_back_to_london_when_timezone_missing():
    with (
        patch("backend.main.get_profile", return_value={}),
        _frozen_at(real_datetime(2026, 6, 15, 23, 30)),
    ):
        assert m.user_today("uid").isoformat() == "2026-06-16"


def test_user_today_falls_back_to_london_on_unknown_timezone_name():
    with (
        patch("backend.main.get_profile", return_value={"timezone": "Not/AZone"}),
        _frozen_at(real_datetime(2026, 6, 15, 23, 30)),
    ):
        assert m.user_today("uid").isoformat() == "2026-06-16"


def test_today_str_matches_user_today():
    with (
        patch("backend.main.get_profile", return_value={"timezone": "Europe/London"}),
        _frozen_at(real_datetime(2026, 6, 15, 23, 30)),
    ):
        assert m.today_str("uid") == "2026-06-16"


# ── /balance picks the user's local day's activities ────────────────────────


def test_balance_at_8pm_la_uses_la_local_day_not_utc_day():
    # 2026-01-10 04:00 UTC is already the 10th in UTC, but still the 9th,
    # 20:00, in Los Angeles — /balance must use the 9th.
    with (
        patch(
            "backend.main.get_profile",
            return_value={"timezone": "America/Los_Angeles", "kcal_target": 2000},
        ),
        _frozen_at(real_datetime(2026, 1, 10, 4, 0)),
        patch("backend.main.get_food_entries", return_value=[]) as get_food_entries,
        patch("backend.main.get_manual_activities", return_value=[]),
        patch(
            "backend.main._fetch_garmin_data",
            new=AsyncMock(return_value=(None, None, {})),
        ),
    ):
        asyncio.run(m._compute_balance("uid"))
        get_food_entries.assert_called_once_with("uid", "2026-01-09")


# ── Garmin cache key is scoped to the user's local date ──────────────────────


def test_garmin_cache_key_includes_user_local_date():
    m._garmin_cache.clear()
    with (
        patch("backend.main.get_profile", return_value={"timezone": "Europe/London"}),
        _frozen_at(real_datetime(2026, 6, 15, 23, 30)),
        patch("backend.main.fetch_garmin", new=AsyncMock(return_value=None)),
        patch("backend.main.fetch_garmin_activities", new=AsyncMock(return_value=None)),
        patch("backend.main.run_in_threadpool", new=AsyncMock(return_value={})),
    ):
        asyncio.run(m._fetch_garmin_data("uid"))

    assert "uid:2026-06-16" in m._garmin_cache
