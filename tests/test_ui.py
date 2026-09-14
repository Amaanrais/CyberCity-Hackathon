"""Tests for Operator Dashboard (Phase 6)."""

import json
import urllib.request
import time
from src.ui.dashboard import TerminalDashboard, DashboardServer


def test_terminal_dashboard_format():
    """Verify ANSI terminal frame contains all required telemetry items."""
    sample_telem = {
        "u_req": 0.85,
        "u_safe": 0.40,
        "flow": 12.5,
        "concentration": 2.45,
        "u_max_inst": 0.65,
        "u_nom": 0.45,
        "m_excess": 320.0,
        "m_budget": 500.0,
        "state": "CLAMPED_CUMULATIVE",
    }
    frame = TerminalDashboard.format_frame(sample_telem)

    # Check for required fields in the rendered output
    assert "85.0%" in frame  # u_req
    assert "40.0%" in frame  # u_safe
    assert "12.5 L/s" in frame  # flow
    assert "2.45 mg/L" in frame  # concentration
    assert "65.0%" in frame  # ceiling
    assert "320.0 mg" in frame  # excess mass
    assert "500.0 mg" in frame  # budget
    assert "CLAMPED: CUMULATIVE" in frame  # state


def test_web_dashboard_server():
    """Verify HTTP server serves UI page and telemetry JSON endpoint."""
    sample_data = {
        "u_req": 0.40,
        "u_safe": 0.40,
        "flow": 10.0,
        "concentration": 2.0,
        "u_max_inst": 1.0,
        "u_nom": 0.40,
        "m_excess": 0.0,
        "m_budget": 500.0,
        "state": "NORMAL",
    }
    server = DashboardServer(telemetry_provider=lambda: sample_data, port=58080)
    server.start()

    time.sleep(0.1)

    try:
        # Check GET /
        with urllib.request.urlopen("http://127.0.0.1:58080/") as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "AQUAPHY" in html

        # Check GET /api/telemetry
        with urllib.request.urlopen("http://127.0.0.1:58080/api/telemetry") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["state"] == "NORMAL"
            assert data["concentration"] == 2.0
    finally:
        server.stop()


def test_web_dashboard_scenario_endpoints():
    """Verify HTTP server handles scenario trigger endpoints."""
    received = []

    def mock_scenario_handler(scen: str):
        received.append(scen)
        return {"status": "ok", "scenario": scen}

    server = DashboardServer(
        telemetry_provider=lambda: {"state": "NORMAL"},
        port=58085,
        run_scenario_handler=mock_scenario_handler,
    )
    server.start()
    time.sleep(0.1)

    try:
        # 1. Test POST /api/demo/scenario?name=acute
        req = urllib.request.Request("http://127.0.0.1:58085/api/demo/scenario?name=acute", data=b"", method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            assert res["status"] == "ok"
            assert res["scenario"] == "acute"

        # 2. Test GET /api/demo/scenario?name=flow_surge
        with urllib.request.urlopen("http://127.0.0.1:58085/api/demo/scenario?name=flow_surge") as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            assert res["scenario"] == "flow_surge"

        # 3. Test POST with JSON body
        body = json.dumps({"scenario": "cumulative"}).encode("utf-8")
        req2 = urllib.request.Request(
            "http://127.0.0.1:58085/api/demo/scenario",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2) as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            assert res["scenario"] == "cumulative"

        assert received == ["acute", "flow_surge", "cumulative"]
    finally:
        server.stop()

