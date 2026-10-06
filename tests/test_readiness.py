"""Tests for backend.main._compute_readiness."""

import backend.main as m


def test_no_data_returns_none():
    assert m._compute_readiness({}) is None


def test_all_signals_good_gives_fresh():
    result = m._compute_readiness(
        {
            "sleep_score": 90,
            "hrv_status": "balanced",
            "body_battery_charged": 85,
        }
    )
    assert result["label"] == "Fresh"
    assert result["score"] >= 80


def test_all_signals_poor_gives_fatigued():
    result = m._compute_readiness(
        {
            "sleep_score": 30,
            "hrv_status": "LOW",
            "body_battery_charged": 20,
        }
    )
    assert result["label"] == "Fatigued"
    assert result["score"] < 40


def test_hrv_status_case_insensitive():
    a = m._compute_readiness({"hrv_status": "balanced"})
    b = m._compute_readiness({"hrv_status": "BALANCED"})
    assert a["score"] == b["score"]


def test_unknown_hrv_status_falls_back_to_baseline_range():
    # No recognized status string, but hrv_last_night is below baseline_low.
    result = m._compute_readiness(
        {
            "hrv_status": "SOME_UNKNOWN_VALUE",
            "hrv_last_night": 30,
            "hrv_baseline_low": 40,
            "hrv_baseline_high": 60,
        }
    )
    assert result is not None
    assert result["components"]["hrv"] == 40  # below-baseline score


def test_hrv_above_baseline_scores_well():
    result = m._compute_readiness(
        {"hrv_last_night": 70, "hrv_baseline_low": 40, "hrv_baseline_high": 60}
    )
    assert result["components"]["hrv"] == 90


def test_hrv_within_baseline_scores_moderate():
    result = m._compute_readiness(
        {"hrv_last_night": 50, "hrv_baseline_low": 40, "hrv_baseline_high": 60}
    )
    assert result["components"]["hrv"] == 75


def test_missing_hrv_and_baseline_omits_hrv_component():
    result = m._compute_readiness({"sleep_score": 70})
    assert "hrv" not in result["components"]


def test_driver_identifies_lowest_component():
    result = m._compute_readiness(
        {
            "sleep_score": 90,
            "hrv_status": "BALANCED",
            "body_battery_charged": 10,
        }
    )
    assert "body battery" in result["driver"]


def test_partial_data_still_scores():
    # Only body battery available (e.g. sleep/HRV fetches failed).
    result = m._compute_readiness({"body_battery_charged": 60})
    assert result["score"] == 60
    assert result["components"] == {"body_battery": 60}


def test_boundary_scores_are_inclusive_correctly():
    # score of exactly 80 -> "Fresh"; exactly 60 -> "Normal"; exactly 40 -> "Tired".
    fresh = m._compute_readiness({"sleep_score": 80, "body_battery_charged": 80})
    assert fresh["label"] == "Fresh"

    normal = m._compute_readiness({"sleep_score": 60, "body_battery_charged": 60})
    assert normal["label"] == "Normal"

    tired = m._compute_readiness({"sleep_score": 40, "body_battery_charged": 40})
    assert tired["label"] == "Tired"
