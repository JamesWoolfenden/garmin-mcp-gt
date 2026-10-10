"""Tests for issue #24 — calibrate the logged balance against the weight
trend to estimate a personal logging bias in kcal/day."""

import random

import backend.main as m


def test_returns_none_below_min_logged_days():
    daily_balances = [-300.0] * 10  # fewer than the 21-day minimum
    weight_readings = [(i, 80.0) for i in range(10)]
    assert m._compute_calibration(daily_balances, weight_readings) is None


def test_returns_none_below_min_weigh_ins():
    daily_balances = [-300.0] * 28
    weight_readings = [(0, 80.0), (1, 80.0)]  # fewer than the 8-reading minimum
    assert m._compute_calibration(daily_balances, weight_readings) is None


def test_under_reporting_bias_noise_free():
    # Weight is flat (no real change) but every logged day shows a 300
    # kcal/day deficit — logs must be under-reporting intake by ~300/day.
    daily_balances = [-300.0] * 28
    weight_readings = [
        (0, 80.0), (1, 80.0), (2, 80.0), (3, 80.0),
        (24, 80.0), (25, 80.0), (26, 80.0), (27, 80.0),
    ]
    result = m._compute_calibration(daily_balances, weight_readings)
    assert result is not None
    assert abs(result["bias_kcal_per_day"] - 300) <= 50
    assert result["window_days"] == 28
    assert result["logged_days"] == 28
    assert result["weigh_ins"] == 8


def test_under_reporting_bias_with_realistic_weight_noise():
    rng = random.Random(42)
    daily_balances = [-300.0] * 28
    weight_readings = [
        (offset, 80.0 + rng.uniform(-0.5, 0.5)) for offset in range(28)
    ]
    result = m._compute_calibration(daily_balances, weight_readings)
    assert result is not None
    assert abs(result["bias_kcal_per_day"] - 300) <= 150


def test_over_reporting_gives_negative_bias():
    # Logs show a surplus (+300/day) but weight didn't change — meaning
    # real intake was lower than logged (over-reporting).
    daily_balances = [300.0] * 28
    weight_readings = [
        (0, 80.0), (1, 80.0), (2, 80.0),
        (25, 80.0), (26, 80.0), (27, 80.0),
        (3, 80.0), (24, 80.0),
    ]
    result = m._compute_calibration(daily_balances, weight_readings)
    assert result is not None
    assert result["bias_kcal_per_day"] < 0


def test_accurate_logging_gives_near_zero_bias():
    # Logged balance matches the real-world weight change implied by it —
    # logs are accurate, bias should be close to zero.
    daily_balances = [-275.0] * 28  # -275*28/7700 = -1.0 kg over the window
    weight_readings = [
        (0, 81.0), (1, 81.0), (2, 81.0), (3, 81.0),
        (24, 80.0), (25, 80.0), (26, 80.0), (27, 80.0),
    ]
    result = m._compute_calibration(daily_balances, weight_readings)
    assert result is not None
    assert abs(result["bias_kcal_per_day"]) <= 50


def test_bias_rounded_to_nearest_50():
    daily_balances = [-313.0] * 28
    weight_readings = [
        (0, 80.0), (1, 80.0), (2, 80.0), (3, 80.0),
        (24, 80.0), (25, 80.0), (26, 80.0), (27, 80.0),
    ]
    result = m._compute_calibration(daily_balances, weight_readings)
    assert result["bias_kcal_per_day"] % 50 == 0
