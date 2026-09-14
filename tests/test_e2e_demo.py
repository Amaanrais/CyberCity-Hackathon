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


