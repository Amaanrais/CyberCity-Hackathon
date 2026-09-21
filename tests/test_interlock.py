import pytest
from app.interlock import SafetyInterlock
from app.models import DecisionType


def test_nominal_tracking():
    interlock = SafetyInterlock()
    decision, actual_dose, reason = interlock.evaluate(
        requested_dose=102.0,
        primary_ppm=102.0,
        verification_ppm=101.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert decision == DecisionType.ALLOWED
    assert actual_dose == 102.0
    assert "Nominal" in reason


def test_hard_bound_rejection():
    interlock = SafetyInterlock()
    # Requested dose > 150 ppm
    decision, actual_dose, reason = interlock.evaluate(
        requested_dose=160.0,
        primary_ppm=160.0,
        verification_ppm=160.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert decision == DecisionType.BLOCKED
    assert actual_dose == 100.0  # Holds last accepted baseline
    assert "HARD_BOUND_EXCEEDED" in reason


def test_rate_of_change_rejection():
    interlock = SafetyInterlock()
    # Jump from 100.0 to 148.0 (delta = 48 > 40 ppm/s limit, but <= 150 hard bound)
    decision, actual_dose, reason = interlock.evaluate(
        requested_dose=148.0,
        primary_ppm=148.0,
        verification_ppm=148.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert decision == DecisionType.BLOCKED
    assert actual_dose == 100.0
    assert "RATE_OF_CHANGE_EXCEEDED" in reason


def test_cross_check_debounce():
    interlock = SafetyInterlock()
    # Single sample disagreement: primary 130 vs verification 100 (30% diff > 15%)
    # Rate of change is 30 <= 40, dose <= 150.
    # First sample: debounces, so not blocked yet
    d1, dose1, r1 = interlock.evaluate(
        requested_dose=130.0,
        primary_ppm=130.0,
        verification_ppm=100.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert d1 == DecisionType.ALLOWED

    # Second consecutive sample of disagreement: trips debounce threshold (2 samples)
    d2, dose2, r2 = interlock.evaluate(
        requested_dose=130.0,
        primary_ppm=130.0,
        verification_ppm=100.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert d2 == DecisionType.BLOCKED
    assert "SENSOR_DISAGREEMENT" in r2


def test_interlock_bypass_when_off():
    interlock = SafetyInterlock()
    interlock.enabled = False
    # Even a catastrophic 11,100 ppm jump passes when interlock switch is OFF
    decision, actual_dose, reason = interlock.evaluate(
        requested_dose=11100.0,
        primary_ppm=11100.0,
        verification_ppm=100.0,
        flow_l_s=50.0,
        actual_flow_l_s=50.0
    )
    assert decision == DecisionType.ALLOWED
    assert actual_dose == 11100.0
    assert "bypassed" in reason.lower()


def test_failsafe_decay():
    interlock = SafetyInterlock()
    # Manually simulate previous elevated accepted dose (e.g. 140 ppm)
    interlock.last_accepted_dose = 140.0

    # 4 consecutive blocks: dose stays at 140.0
    for _ in range(4):
        d, dose, r = interlock.evaluate(11100.0, 11100.0, 100.0, 50.0, 50.0)
        assert d == DecisionType.BLOCKED
        assert dose == 140.0

    # 5th block: fail-safe decay triggers, stepping dose down toward 100.0
    d5, dose5, r5 = interlock.evaluate(11100.0, 11100.0, 100.0, 50.0, 50.0)
    assert d5 == DecisionType.BLOCKED
    assert dose5 < 140.0
    assert "FAIL-SAFE DECAY ACTIVE" in r5
