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
