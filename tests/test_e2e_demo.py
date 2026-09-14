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

