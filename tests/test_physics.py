"""Unit tests for CSTR hydraulic mass balance and numerical simulation (Phase 1 & Phase 8)."""

import math
import pytest
from src.simulation.cstr import CSTRSimulation, CSTRParameters


def test_parameter_dimensional_sanity():
    """Verify default physical constants match specification in docs/architecture.md."""
    params = CSTRParameters()
    assert params.V == 1000.0
    assert params.Q_nominal == 10.0
    assert params.C_in == 0.0
    assert params.C_target == 2.0
    assert params.C_max == 4.0
    assert params.k_pump == 100.0
    assert params.k_decay == 0.01
    assert params.dt == 0.1


def test_normal_operating_point_is_stable():
    """Verify that at nominal conditions (u=0.40, Q=10.0), C=2.0 mg/L is an exact equilibrium."""
    sim = CSTRSimulation()
    assert sim.concentration == 2.0
    assert sim.flow == 10.0

    # Theoretical dC/dt should be exactly 0.0
    dC_dt = sim.compute_dC_dt(u=0.40, Q=10.0, C=2.0)
    assert abs(dC_dt) < 1e-12

    # Step for 100 seconds (1000 steps) and ensure concentration does not drift
    for _ in range(1000):
        c = sim.step(u=0.40, Q=10.0)

    assert pytest.approx(c, rel=1e-6) == 2.0
    assert pytest.approx(sim.time, rel=1e-6) == 100.0


def test_concentration_responds_to_increased_dosing():
    """Verify concentration increases monotonically towards theoretical steady state when pump increases."""
    sim = CSTRSimulation()
    # At u=0.80, Q=10.0: C_ss = (0 + 100 * 0.8) / (10 + 0.01 * 1000) = 80 / 20 = 4.0 mg/L
    expected_ss = sim.steady_state_concentration(u=0.80, Q=10.0)
    assert expected_ss == 4.0

    previous_c = sim.concentration
    # After 50s (500 steps, tau=50s), C = 4.0 - 2.0*e^(-1) = ~3.26 mg/L
    for _ in range(500):  # 50 seconds
        c = sim.step(u=0.80, Q=10.0)
        assert c >= previous_c  # Monotonically increasing
        previous_c = c

    # After 50s (1 tau), should have risen past 3.2 mg/L
    assert sim.concentration > 3.2
    assert sim.concentration < 4.0


def test_concentration_responds_to_flow_increase():
    """Verify higher flow increases dilution, driving concentration downward for fixed dosing."""
    sim = CSTRSimulation()
    # At Q=20.0 L/s, u=0.40: C_ss = (0 + 100 * 0.4) / (20 + 0.01 * 1000) = 40 / 30 = 1.333 mg/L
    expected_ss = sim.steady_state_concentration(u=0.40, Q=20.0)
    assert pytest.approx(expected_ss, rel=1e-3) == 40.0 / 30.0

    previous_c = sim.concentration
    for _ in range(300):  # 30 seconds
        c = sim.step(u=0.40, Q=20.0)
        assert c <= previous_c  # Monotonically decreasing
        previous_c = c

    assert sim.concentration < 2.0
    assert sim.concentration > 1.3


def test_euler_numerical_stability():
    """Verify simulation remains stable and non-negative even under zero dosing and extreme conditions."""
    sim = CSTRSimulation(initial_C=5.0)
    # Turn pump off completely (u=0.0). Decay time constant tau = 1 / (Q/V + k_decay) = 50s.
    # After 350s (3500 steps, ~7 time constants), C drops by factor of e^7 (~1096)
    for _ in range(3500):
        c = sim.step(u=0.0, Q=10.0)
        assert c >= 0.0  # Physically bounded to non-negative

    # Should asymptotically approach zero (< 0.01 mg/L)
    assert sim.concentration < 0.01


def test_safe_numerical_handling_zero_flow():
    """Verify Q=0 is handled safely without division by zero or negative state."""
    sim = CSTRSimulation(initial_C=2.0)
    # At Q=0, dC/dt = (k_pump * u)/V - k_decay * C
    dC_dt = sim.compute_dC_dt(u=0.40, Q=0.0, C=2.0)
    # dC_dt = (100 * 0.4)/1000 - 0.01 * 2.0 = 0.04 - 0.02 = +0.02 mg/(L*s)
    assert pytest.approx(dC_dt, rel=1e-6) == 0.02

    c = sim.step(u=0.40, Q=0.0)
    assert c > 2.0


def test_safe_numerical_handling_volume_near_zero():
    """Verify V approaching zero does not cause unhandled ZeroDivisionError."""
    sim = CSTRSimulation()
    # Direct calculation with tiny V
    dC_dt = sim.compute_dC_dt(u=0.5, Q=10.0, C=2.0, V=0.0)
    assert not math.isnan(dC_dt)
    assert not math.isinf(dC_dt)

    dC_dt_tiny = sim.compute_dC_dt(u=0.5, Q=10.0, C=2.0, V=1e-9)
    assert not math.isnan(dC_dt_tiny)
    assert not math.isinf(dC_dt_tiny)


def test_bounded_pump_and_concentration_inputs():
    """Verify that pump commands outside [0, 1] are clamped properly."""
    sim = CSTRSimulation()
    # Negative pump command should be treated as 0.0
    dC_dt_neg = sim.compute_dC_dt(u=-0.5, Q=10.0, C=2.0)
    dC_dt_zero = sim.compute_dC_dt(u=0.0, Q=10.0, C=2.0)
    assert dC_dt_neg == dC_dt_zero

    # Command > 1.0 should be treated as 1.0
    dC_dt_over = sim.compute_dC_dt(u=1.5, Q=10.0, C=2.0)
    dC_dt_max = sim.compute_dC_dt(u=1.0, Q=10.0, C=2.0)
    assert dC_dt_over == dC_dt_max
