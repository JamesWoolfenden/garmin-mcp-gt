"""Tests for issue #22 — calorie burn must use one basis (net active kcal)
whether or not there's a Garmin activity, and manual entries that likely
double-count a synced Garmin activity get flagged."""

import asyncio
from unittest.mock import AsyncMock, patch

import backend.main as m


# ── _activity_net_kcal ───────────────────────────────────────────────────────


def test_activity_net_kcal_subtracts_bmr():
    assert m._activity_net_kcal({"calories": 800, "bmrCalories": 150}) == (650, False)


def test_activity_net_kcal_falls_back_to_gross_when_bmr_missing():
    # Activities synced from a third party (Strava, Zwift, ...) may not
    # carry bmrCalories — fall back to gross kcal, flagged as estimated.
    assert m._activity_net_kcal({"calories": 800}) == (800, True)


# ── _is_possible_duplicate ───────────────────────────────────────────────────


def test_is_possible_duplicate_matches_on_garmin_activity_type():
    garmin_activities = [{"type": "road_biking", "name": "Morning Ride"}]
    assert (
        m._is_possible_duplicate({"name": "road biking session"}, garmin_activities)
        is True
    )


def test_is_possible_duplicate_matches_on_garmin_activity_name():
    garmin_activities = [{"type": "cycling", "name": "Zwift Ride"}]
    assert m._is_possible_duplicate({"name": "zwift ride - logged manually"}, garmin_activities) is True


def test_is_possible_duplicate_false_when_unrelated():
    garmin_activities = [{"type": "road_biking", "name": "Morning Ride"}]
    assert m._is_possible_duplicate({"name": "swimming"}, garmin_activities) is False


def test_is_possible_duplicate_false_without_garmin_activities():
    assert m._is_possible_duplicate({"name": "road biking session"}, None) is False
    assert m._is_possible_duplicate({"name": "road biking session"}, []) is False


# ── _compute_balance kcal basis ──────────────────────────────────────────────

_REC_STUB = {"status": "on_track", "recommendation": "ok"}


def _run_balance(uid="uid", for_date=None, garmin=None, activities=None, manual=None):
    manual = manual or []
    with (
        patch("backend.main.today_str", return_value="2026-06-16"),
        patch("backend.main.get_food_entries", return_value=[]),
        patch("backend.main.get_profile", return_value={"kcal_target": 2000}),
        patch("backend.main.get_manual_activities", return_value=manual),
        patch(
            "backend.main._fetch_garmin_data",
            new=AsyncMock(return_value=(garmin, activities, {})),
        ),
        patch("backend.main.run_in_threadpool", new=AsyncMock(return_value=_REC_STUB)),
    ):
        return asyncio.run(m._compute_balance(uid, for_date))


def test_ride_plus_steps_uses_daily_active_kcal_not_gross_ride_kcal():
    # activeKilocalories (1200) already covers the ride plus the day's 10k
    # steps — it must be the sole Garmin burn figure, not the ride's own
    # (higher, gross) per-activity kcal.
    garmin = {
        "active_kcal": 1200,
        "steps": 10000,
        "distance_km": 7.0,
        "active_minutes": 90,
        "body_battery": {},
    }
    activities = [
        {
            "name": "Evening ride",
            "type": "cycling",
            "duration_min": 60,
            "distance_km": 20,
            "kcal": 900,  # net, display-only
            "kcal_estimated": False,
            "avg_power_w": 180,
        }
    ]
    result = _run_balance(garmin=garmin, activities=activities)
    assert result["kcal_burned"] == 1200


def test_third_party_synced_activity_counted_exactly_once():
    garmin = {
        "active_kcal": 800,
        "steps": 3000,
        "distance_km": 2.0,
        "active_minutes": 30,
        "body_battery": {},
    }
    activities = [
        {
            "name": "Zwift ride",
            "type": "virtual_cycling",
            "duration_min": 45,
            "distance_km": 18,
            "kcal": 500,
            "kcal_estimated": True,
            "avg_power_w": 150,
        }
    ]
    result = _run_balance(garmin=garmin, activities=activities)
    assert result["kcal_burned"] == 800


def test_manual_duplicate_of_garmin_activity_is_flagged():
    garmin = {
        "active_kcal": 600,
        "steps": 1000,
        "distance_km": 1.0,
        "active_minutes": 10,
        "body_battery": {},
    }
    activities = [
        {
            "name": "Morning ride",
            "type": "road_biking",
            "duration_min": 40,
            "distance_km": 15,
            "kcal": 400,
            "kcal_estimated": False,
            "avg_power_w": 170,
        }
    ]
    manual = [{"id": "m1", "name": "road biking session", "kcal": 400}]
    result = _run_balance(garmin=garmin, activities=activities, manual=manual)
    [entry] = [a for a in result["manual_activities"] if a["id"] == "m1"]
    assert entry["possible_duplicate"] is True


def test_manual_entry_unrelated_to_garmin_activity_not_flagged():
    garmin = {
        "active_kcal": 600,
        "steps": 1000,
        "distance_km": 1.0,
        "active_minutes": 10,
        "body_battery": {},
    }
    activities = [
        {
            "name": "Morning ride",
            "type": "road_biking",
            "duration_min": 40,
            "distance_km": 15,
            "kcal": 400,
            "kcal_estimated": False,
            "avg_power_w": 170,
        }
    ]
    manual = [{"id": "m2", "name": "swimming", "kcal": 250}]
    result = _run_balance(garmin=garmin, activities=activities, manual=manual)
    [entry] = [a for a in result["manual_activities"] if a["id"] == "m2"]
    assert entry["possible_duplicate"] is False
