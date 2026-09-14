"""Unit tests for AquaPhy Physics Engine and Interlock Invariants (Phase 3 & Phase 8)."""

import pytest
from src.interlock.physics_engine import (
    PhysicsEngine,
    DefenseState,
    InterlockParameters,
)
from src.simulation.cstr import CSTRParameters


def test_algebraic_derivation_instantaneous_bound():
    """Verify that u_max_inst exactly keeps C_next <= C_max under forward Euler."""
    engine = PhysicsEngine()
    params = engine.cstr
    dt = 0.1
    Q = 10.0
    C = 3.5  # Close to C_max (4.0)

    u_max = engine.compute_instantaneous_ceiling(Q=Q, C=C, dt=dt)

    # Plug u_max into forward Euler update:
    dC_dt = (Q / params.V) * (params.C_in - C) + (params.k_pump * u_max) / params.V - params.k_decay * C
    c_next = C + dt * dC_dt

    # The predicted next concentration should be <= C_max (within numerical precision)
    assert c_next <= params.C_max + 1e-9


def test_instantaneous_ceiling_when_already_at_cmax():
    """When C >= C_max, instantaneous ceiling should force pump to 0 or minimum."""
    engine = PhysicsEngine()
    u_max = engine.compute_instantaneous_ceiling(Q=10.0, C=4.0, dt=0.1)
    # At C=4.0, term1=0, term2=-10*(0-4)=40, term3=0.01*1000*4=40. (40+40)/100 = 0.8
    # Notice: at C=4.0, dC/dt = -10/1000*4 + 100*u/1000 - 0.01*4 = -0.04 + 0.1*u - 0.04 = 0.1*u - 0.08
    # For C_next <= 4.0, dC/dt <= 0 => 0.1*u <= 0.08 => u <= 0.80!
    # If C = 4.5 (> C_max), u_max should be even lower or 0.
    assert u_max <= 0.80

    u_max_over = engine.compute_instantaneous_ceiling(Q=10.0, C=4.5, dt=0.1)
    # term1 = (1000/0.1)*(4.0 - 4.5) = -5000 mg/s. u_raw < 0, so clamped to 0.0!
    assert u_max_over == 0.0


def test_nominal_baseline_calculation():
    """Verify nominal baseline matches analytical steady-state dosing for C_target."""
    engine = PhysicsEngine()
    # At Q = 10.0 L/s, C_target = 2.0 mg/L:
    # m_dot_nom = 10 * (2.0 - 0.0) + 0.01 * 1000 * 2.0 = 20 + 20 = 40.0 mg/s
    # u_nom = 40.0 / 100.0 = 0.40
    m_dot_nom, u_nom = engine.compute_nominal_baseline(Q=10.0)
    assert pytest.approx(m_dot_nom, rel=1e-6) == 40.0
    assert pytest.approx(u_nom, rel=1e-6) == 0.40


def test_attacker_history_independence():
    """Verify that nominal baseline does NOT shift regardless of what commands were sent in the past."""
    engine = PhysicsEngine()

    # Baseline at nominal flow Q=10
    _, u_nom_initial = engine.compute_nominal_baseline(Q=10.0)
    assert pytest.approx(u_nom_initial, rel=1e-6) == 0.40

    # Attacker injects a series of malicious or drifting setpoints
    t = 0.0
    for malicious_u in [0.45, 0.50, 0.60, 0.90, 0.99]:
        t += 1.0
        engine.evaluate(u_req=malicious_u, Q=10.0, C=2.0, current_time=t, dt=1.0)

    # Baseline must remain strictly invariant to attacker history
    _, u_nom_after = engine.compute_nominal_baseline(Q=10.0)
    assert pytest.approx(u_nom_after, rel=1e-6) == 0.40


def test_flow_coupling_dynamically_adjusts_limits():
    """Verify flow surge increases nominal demand baseline legitimately without spurious clamping."""
    engine = PhysicsEngine()
    # When flow doubles to Q=20.0 L/s:
    # m_dot_nom = 20 * (2.0 - 0.0) + 0.01 * 1000 * 2.0 = 40 + 20 = 60.0 mg/s
    # u_nom = 60 / 100 = 0.60
    m_dot_nom_high, u_nom_high = engine.compute_nominal_baseline(Q=20.0)
    assert pytest.approx(m_dot_nom_high, rel=1e-6) == 60.0
    assert pytest.approx(u_nom_high, rel=1e-6) == 0.60

    # Operator sends legitimate increase to 0.60 to meet surge demand
    res = engine.evaluate(u_req=0.60, Q=20.0, C=2.0, current_time=1.0, dt=1.0)
    assert res.decision == DefenseState.NORMAL
    assert pytest.approx(res.u_safe, rel=1e-6) == 0.60
    assert res.m_excess == 0.0  # Zero excess because it matches nominal for Q=20


def test_instantaneous_clamping_on_acute_spike():
    """Verify acute spike (u=1.0 when C is high) is clamped to u_max_inst."""
    engine = PhysicsEngine()
    # Near C_max: C = 3.99 mg/L, Q = 10.0 L/s, dt = 0.1 s
    # (V/dt)*(C_max - C) = (1000/0.1)*(0.01) = 100 mg/s
    # - Q*(C_in - C) = -10*(-3.99) = 39.9 mg/s
    # k_decay*V*C = 0.01*1000*3.99 = 39.9 mg/s
    # Total numerator = 100 + 39.9 + 39.9 = 179.8 mg/s => u_raw = 1.798 (clamped to 1.0)
    # But if dt = 1.0s or C is closer:
    # Let's test C = 3.99 with dt = 1.0s:
    # (V/dt)*(C_max - C) = 1000 * 0.01 = 10 mg/s
    # Total = 10 + 39.9 + 39.9 = 89.8 mg/s => u_max = 0.898
    res = engine.evaluate(u_req=1.0, Q=10.0, C=3.99, current_time=1.0, dt=1.0)
    assert res.decision == DefenseState.CLAMPED_INSTANTANEOUS
    assert res.u_safe < 1.0
    assert pytest.approx(res.u_safe, rel=1e-2) == 0.898


def test_cumulative_budget_accumulation():
    """Verify excess dosing accumulates in physical mass units (mg) over time."""
    engine = PhysicsEngine(InterlockParameters(mass_budget=500.0, window_duration=60.0))
    # At Q=10.0, u_nom = 0.40 (m_dot_nom = 40 mg/s).
    # Request u = 0.50 (m_dot_req = 50 mg/s). Excess rate = 10 mg/s.
    t = 0.0
    for _ in range(20):  # 20 seconds
        t += 1.0
        res = engine.evaluate(u_req=0.50, Q=10.0, C=2.0, current_time=t, dt=1.0)
        assert res.decision == DefenseState.NORMAL  # Under 500mg budget

    # After 20 seconds at 10 mg/s excess, M_excess should be 200 mg
    assert pytest.approx(res.m_excess, rel=1e-3) == 200.0


def test_slow_ramp_cumulative_clamping():
    """Verify slow insidious ramp eventually exhausts mass budget and is clamped to u_nom."""
    engine = PhysicsEngine(InterlockParameters(mass_budget=500.0, window_duration=60.0))
    # At Q=10.0, u_nom = 0.40.
    # Attacker requests u = 0.50 (excess = 10 mg/s).
    # Budget is 500 mg, so after 50 seconds, budget is exceeded.
    t = 0.0
    res = None
    for _ in range(55):  # 55 seconds
        t += 1.0
        res = engine.evaluate(u_req=0.50, Q=10.0, C=2.0, current_time=t, dt=1.0)

    assert res is not None
    assert res.decision == DefenseState.CLAMPED_CUMULATIVE
    # Clamped to u_nom = 0.40
    assert pytest.approx(res.u_safe, rel=1e-3) == 0.40
    assert res.m_excess > 500.0


def test_edge_cases_zero_flow_and_near_zero_volume():
    """Verify evaluation handles Q=0 and tiny V gracefully without crashing."""
    engine = PhysicsEngine()
    # Q = 0
    res_zero_q = engine.evaluate(u_req=0.50, Q=0.0, C=2.0, current_time=1.0, dt=0.1)
    assert res_zero_q.decision in [DefenseState.NORMAL, DefenseState.CLAMPED_INSTANTANEOUS]

    # Extreme dt or out-of-range commands
    res_neg = engine.evaluate(u_req=-0.5, Q=10.0, C=2.0, current_time=2.0, dt=0.1)
    assert res_neg.u_safe == 0.0
    assert res_neg.decision == DefenseState.NORMAL

    res_huge = engine.evaluate(u_req=2.5, Q=10.0, C=2.0, current_time=3.0, dt=0.1)
    assert res_huge.u_req == 1.0  # Bounded to 1.0


def test_negative_and_out_of_range_commands():
    """Verify negative and excessive setpoints (>1.0) are safely bounded."""
    engine = PhysicsEngine()
    # Negative setpoint
    res_neg = engine.evaluate(u_req=-0.25, Q=10.0, C=2.0)
    assert res_neg.u_req == 0.0
    assert res_neg.u_safe == 0.0
    assert res_neg.decision == DefenseState.NORMAL

    # Out of range positive setpoint
    res_pos = engine.evaluate(u_req=1.50, Q=10.0, C=2.0)
    assert res_pos.u_req == 1.0
    # Must be clamped by instantaneous ceiling
    assert res_pos.u_safe <= 1.0
    assert res_pos.decision in [DefenseState.NORMAL, DefenseState.CLAMPED_INSTANTANEOUS]


def test_failsafe_behavior():
    """Verify last known safe setpoint is stored and available on engine."""
    engine = PhysicsEngine()
    assert engine.last_safe_u == 0.40

    res = engine.evaluate(u_req=0.45, Q=10.0, C=2.0)
    assert engine.last_safe_u == res.u_safe


def test_cumulative_tracking_idle_gap_silence():
    """Verify that an elevated command followed by 10-15s of silence continues accumulating
    excess mass and eventually trips the budget without requiring additional attacker writes.
    """
    engine = PhysicsEngine(InterlockParameters(mass_budget=75.0, window_duration=60.0))
    # Initial command u = 0.55 at t = 0.0 (nominal is 0.40, excess rate = 15 mg/s)
    res0 = engine.evaluate(u_req=0.55, Q=10.0, C=2.0, current_time=0.0)
    assert res0.decision == DefenseState.NORMAL
    assert res0.u_safe == 0.55

    # Attacker sends NO MORE WRITES for 15 seconds of process time
    tripped_at_step = None
    res_last = None
    for step in range(1, 16):
        t = float(step)
        res_tick = engine.tick(Q=10.0, C=2.0, current_time=t)
        if res_tick.decision == DefenseState.CLAMPED_CUMULATIVE and tripped_at_step is None:
            tripped_at_step = step
        res_last = res_tick

    assert tripped_at_step is not None
    assert tripped_at_step <= 6  # 75 mg / 15 mg/s = 5 seconds
    assert res_last is not None
    assert res_last.decision == DefenseState.CLAMPED_CUMULATIVE
    assert pytest.approx(res_last.u_safe, rel=1e-3) == 0.40
    assert pytest.approx(engine.active_u, rel=1e-3) == 0.40


def test_packet_rate_independence():
    """Verify that sending 50 rapid packets over 0.1s does NOT accumulate 50x mass."""
    engine = PhysicsEngine(InterlockParameters(mass_budget=500.0, window_duration=60.0))
    engine.evaluate(u_req=0.50, Q=10.0, C=2.0, current_time=0.0)

    # Rapid burst of 50 packets spanning 0.1 seconds
    res = None
    for i in range(1, 51):
        t = 0.1 * (i / 50.0)
        res = engine.evaluate(u_req=0.50, Q=10.0, C=2.0, current_time=t)

    assert res is not None
    # In 0.1s at 10 mg/s excess, exactly 1.0 mg should accumulate, NOT 50x
    assert pytest.approx(res.m_excess, rel=1e-2) == 1.0


def test_physics_engine_concurrency_stress():
    """HIGH PRIORITY FIX 2: Stress test concurrent evaluate() and tick() invocations.

    Verifies that:
    1. No exceptions (race conditions, deque mutation during iteration) occur.
    2. Cumulative excess mass remains within physically possible bounds:
       M_excess <= k_pump * sum(dt).
    3. Engine internal state properties are consistent and non-corrupted.
    """
    import threading
    engine = PhysicsEngine(InterlockParameters(mass_budget=200.0, window_duration=60.0))
    exceptions: list[Exception] = []

    # 6 concurrent worker threads: 4 writers calling evaluate(), 2 background loops calling tick()
    num_writers = 4
    num_tickers = 2
    steps_per_thread = 150
    dt_step = 0.01  # 10 ms process time per call

    def writer_worker(thread_id: int):
        try:
            for i in range(steps_per_thread):
                u_cmd = 0.45 if (i % 2 == 0) else 0.55
                res = engine.evaluate(u_req=u_cmd, Q=10.0, C=2.0, dt=dt_step)
                assert res.u_safe <= 1.0
                assert res.u_safe >= 0.0
        except Exception as e:
            exceptions.append(e)

    def ticker_worker(thread_id: int):
        try:
            for i in range(steps_per_thread):
                res = engine.tick(Q=10.0, C=2.0, dt=dt_step)
                assert res.u_safe <= 1.0
                assert res.u_safe >= 0.0
        except Exception as e:
            exceptions.append(e)

    threads: list[threading.Thread] = []
    for w in range(num_writers):
        threads.append(threading.Thread(target=writer_worker, args=(w,)))
    for t in range(num_tickers):
        threads.append(threading.Thread(target=ticker_worker, args=(t,)))

    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10.0)

    # Invariant 1: No exceptions occurred during concurrent execution
    assert len(exceptions) == 0, f"Concurrent execution raised exceptions: {exceptions}"

    # Invariant 2: Total process time elapsed = (num_writers + num_tickers) * steps_per_thread * dt_step
    total_calls = (num_writers + num_tickers) * steps_per_thread
    total_dt = total_calls * dt_step
    max_physical_mass = engine.cstr.k_pump * total_dt

    m_excess = engine.get_cumulative_excess()
    assert 0.0 <= m_excess <= max_physical_mass + 1e-6, (
        f"Cumulative excess mass {m_excess:.2f} exceeded physical bound {max_physical_mass:.2f}"
    )

    # Invariant 3: Active pump setpoint and safety state are valid
    assert 0.0 <= engine.active_u <= 1.0
    assert 0.0 <= engine.last_safe_u <= 1.0



