"""End-to-end scenario integration test (Phase 8)."""

from demo.run_demo import AquaPhyDemoOrchestrator


def test_end_to_end_demo_scenario():
    """Verify that the full 5-phase demo scenario runs cleanly and passes all assertions."""
    orchestrator = AquaPhyDemoOrchestrator(
        plc_port=55201,
        proxy_port=55200,
        web_port=58081,
        enable_web=False,
        interactive=False,
        speed=2.0,
        mass_budget=75.0,
    )

    try:
        orchestrator.start()
        success = orchestrator.run_scenario()
        assert success is True
    finally:
        orchestrator.stop()


def test_end_to_end_demo_scenario_fast_speed_4():
    """HIGH PRIORITY FIX 4: Verify full demo scenario produces identical success at --speed 4.0."""
    orchestrator = AquaPhyDemoOrchestrator(
        plc_port=55203,
        proxy_port=55202,
        web_port=58082,
        enable_web=False,
        interactive=False,
        speed=4.0,
        mass_budget=75.0,
    )

    try:
        orchestrator.start()
        success = orchestrator.run_scenario()
        assert success is True
    finally:
        orchestrator.stop()


def test_orchestrator_reset_restores_complete_system():
    """Verify that reset_plant restores the complete system and allows re-running."""
    orchestrator = AquaPhyDemoOrchestrator(
        plc_port=55205,
        proxy_port=55204,
        web_port=58083,
        enable_web=False,
        interactive=False,
        speed=4.0,
        mass_budget=75.0,
    )

    try:
        orchestrator.start()
        # 1. Run full 5-phase scenario ending in Phase 4 (PLC stopped)
        success = orchestrator.run_scenario()
        assert success is True
        assert orchestrator.proxy.current_state.value == "FAILSAFE_HOLD"

        # 2. Trigger complete system reset
        telem = orchestrator.reset_plant()

        # 3. Verify all 8 system restoration invariants
        assert orchestrator.plc.is_running is True, "PLC should be running"
        assert orchestrator.proxy._downstream_healthy is True, "Proxy downstream should be healthy"
        assert orchestrator.engine.get_cumulative_excess() == 0.0, "Cumulative excess should be 0"
        assert orchestrator.proxy.current_state.value == "NORMAL", "Defense state should be NORMAL"
        assert orchestrator.plc.get_flow_rate() == 10.0, "Flow Q should be 10 L/s"
        assert orchestrator.plc.get_pump_setpoint() == 0.40, "Pump setpoint should be 40%"
        assert abs(orchestrator.plc.get_concentration() - 2.0) < 0.1, "Effluent C should be ~2 mg/L"
        assert telem["phase_title"] == "READY FOR DEMONSTRATION", "Dashboard should say READY FOR DEMONSTRATION"
        assert telem["demo_status"] == "IDLE", "Demo status should be IDLE"

        # 4. Verify scenario can be executed again after reset
        success2 = orchestrator.run_scenario()
        assert success2 is True
    finally:
        orchestrator.stop()


def test_orchestrator_individual_scenarios():
    """Verify that each of the 5 demo scenarios runs independently and halts on expected final state."""
    orchestrator = AquaPhyDemoOrchestrator(
        plc_port=55207,
        proxy_port=55206,
        web_port=58084,
        enable_web=False,
        interactive=False,
        speed=4.0,
        mass_budget=75.0,
    )

    try:
        orchestrator.start()

        # 1. NORMAL scenario
        ok1 = orchestrator.run_individual_scenario("normal", presentation_mode=False)
        assert ok1 is True
        t1 = orchestrator._get_current_telemetry()
        assert t1["state"] == "NORMAL"
        assert t1["phase_title"] == "NORMAL"
        assert abs(t1["u_safe"] - 0.40) < 0.01

        # 2. ACUTE scenario
        ok2 = orchestrator.run_individual_scenario("acute", presentation_mode=False)
        assert ok2 is True
        t2 = orchestrator._get_current_telemetry()
        assert t2["state"] == "CLAMPED_INSTANTANEOUS"
        assert t2["phase_title"] == "ATTACK BLOCKED"
        assert abs(t2["u_safe"] - 0.80) < 0.02

        # 3. FLOW SURGE scenario
        ok3 = orchestrator.run_individual_scenario("flow_surge", presentation_mode=False)
        assert ok3 is True
        t3 = orchestrator._get_current_telemetry()
        assert t3["state"] == "NORMAL"
        assert t3["phase_title"] == "LEGITIMATE SURGE ACCEPTED"
        assert abs(t3["u_safe"] - 0.56) < 0.02

        # 4. CUMULATIVE scenario
        ok4 = orchestrator.run_individual_scenario("cumulative", presentation_mode=False)
        assert ok4 is True
        t4 = orchestrator._get_current_telemetry()
        assert t4["state"] == "CLAMPED_CUMULATIVE"
        assert t4["phase_title"] == "CUMULATIVE LIMIT"
        assert abs(t4["u_safe"] - 0.40) < 0.02
        assert t4["m_excess"] >= 75.0

        # 5. FAILSAFE scenario
        ok5 = orchestrator.run_individual_scenario("failsafe", presentation_mode=False)
        assert ok5 is True
        t5 = orchestrator._get_current_telemetry()
        assert t5["state"] == "FAILSAFE_HOLD"
        assert t5["phase_title"] == "FAILSAFE HOLD"
        assert abs(t5["u_safe"] - 0.40) < 0.02
    finally:
        orchestrator.stop()



