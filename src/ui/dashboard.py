"""AquaPhy Operator Telemetry Dashboard (Phase 6).

Provides:
1. TerminalDashboard: ANSI-colored, real-time live console view.
2. DashboardServer: Lightweight local HTTP/JSON/SSE server for browser monitoring.
"""

from __future__ import annotations
import http.server
import json
import socketserver
import threading
import time
from typing import Any, Callable, Dict, Optional


def make_bar(val: float, max_val: float = 1.0, width: int = 20) -> str:
    """Render a clean text progress bar."""
    ratio = max(0.0, min(1.0, val / max_val if max_val > 0 else 0.0))
    filled = int(round(ratio * width))
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {ratio * 100:5.1f}%"


class TerminalDashboard:
    """Renders formatted real-time ANSI terminal dashboard frames."""

    # ANSI color codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"
    CLEAR_SCREEN = "\033[2J\033[H"

    @classmethod
    def format_frame(cls, telem: Dict[str, Any]) -> str:
        """Format a single telemetry snapshot into a formatted status board."""
        u_req = telem.get("u_req", 0.40)
        u_safe = telem.get("u_safe", 0.40)
        flow = telem.get("flow", 10.0)
        c = telem.get("concentration", 2.0)
        u_ceil = telem.get("u_max_inst", 1.0)
        u_nom = telem.get("u_nom", 0.40)
        m_excess = telem.get("m_excess", 0.0)
        m_budget = telem.get("m_budget", 500.0)
        state = telem.get("state", "NORMAL")

        # Colorize state badge
        if state == "NORMAL":
            state_badge = f"{cls.GREEN}{cls.BOLD}[ NORMAL ]{cls.RESET}"
        elif state == "CLAMPED_INSTANTANEOUS":
            state_badge = f"{cls.YELLOW}{cls.BOLD}[ CLAMPED: INSTANTANEOUS ]{cls.RESET}"
        elif state == "CLAMPED_CUMULATIVE":
            state_badge = f"{cls.RED}{cls.BOLD}[ CLAMPED: CUMULATIVE ]{cls.RESET}"
        elif state == "FAILSAFE_HOLD":
            state_badge = f"{cls.MAGENTA}{cls.BOLD}[ FAILSAFE: HOLD ]{cls.RESET}"
        else:
            state_badge = f"{cls.BOLD}[ {state} ]{cls.RESET}"

        conc_color = cls.GREEN if c <= 3.5 else (cls.YELLOW if c <= 4.0 else cls.RED)
        clamped_flag = f"{cls.RED}{cls.BOLD}CLAMPED!{cls.RESET}" if abs(u_req - u_safe) > 0.001 else f"{cls.GREEN}PASS{cls.RESET}"

        lines = [
            f"{cls.CYAN}{cls.BOLD}========================================================================{cls.RESET}",
            f"{cls.CYAN}{cls.BOLD}          AQUAPHY — INLINE PHYSICAL SAFETY INTERLOCK CONSOLE           {cls.RESET}",
            f"{cls.CYAN}{cls.BOLD}========================================================================{cls.RESET}",
            f" Defense Operational State : {state_badge}",
            f" Interlock Action          : {clamped_flag}",
            f"------------------------------------------------------------------------",
            f"{cls.BOLD}1. CHEMICAL DOSING ACTUATION STREAM:{cls.RESET}",
            f"  Requested Command (u_req)  : {u_req * 100:5.1f}%  {make_bar(u_req, 1.0, 16)}",
            f"  Safe Forwarded    (u_safe) : {u_safe * 100:5.1f}%  {make_bar(u_safe, 1.0, 16)}",
            f"  Instantaneous Ceiling (u_max): {u_ceil * 100:5.1f}%",
            f"  Nominal Baseline      (u_nom): {u_nom * 100:5.1f}%",
            f"------------------------------------------------------------------------",
            f"{cls.BOLD}2. PHYSICAL PROCESS TELEMETRY (CSTR CONTACT TANK):{cls.RESET}",
            f"  Raw Water Inflow Flow (Q)  : {flow:5.1f} L/s",
            f"  Effluent Concentration (C) : {conc_color}{c:5.2f} mg/L{cls.RESET} (Target: 2.00 mg/L | Max: 4.00 mg/L)",
            f"------------------------------------------------------------------------",
            f"{cls.BOLD}3. CUMULATIVE EXCESS CHEMICAL MASS TRACKER:{cls.RESET}",
            f"  Cumulative Excess Mass (M) : {m_excess:6.1f} mg / {m_budget:.1f} mg  {make_bar(m_excess, m_budget, 16)}",
            f"{cls.CYAN}{cls.BOLD}========================================================================{cls.RESET}",
        ]
        return "\n".join(lines)


class DashboardServer:
    """Lightweight web server providing live browser UI and JSON telemetry."""

    def __init__(
        self,
        telemetry_provider: Callable[[], Dict[str, Any]],
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> None:
        self.telemetry_provider = telemetry_provider
        self.host = host
        self.port = port
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def _build_html(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AquaPhy Physical Interlock Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0b0f19;
    --card: #151c2e;
    --border: #232f48;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --accent: #38bdf8;
    --green: #22c55e;
    --yellow: #eab308;
    --red: #ef4444;
    --purple: #a855f7;
  }
  body {
    margin: 0;
    padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  .container { max-width: 900px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }
  h1 { font-size: 1.5rem; margin: 0; color: var(--accent); }
  .badge { padding: 6px 14px; border-radius: 9999px; font-weight: bold; font-size: 0.85rem; letter-spacing: 0.05em; }
  .badge-NORMAL { background: rgba(34,197,94,0.2); color: var(--green); border: 1px solid var(--green); }
  .badge-CLAMPED_INSTANTANEOUS { background: rgba(234,179,8,0.2); color: var(--yellow); border: 1px solid var(--yellow); }
  .badge-CLAMPED_CUMULATIVE { background: rgba(239,68,68,0.2); color: var(--red); border: 1px solid var(--red); }
  .badge-FAILSAFE_HOLD { background: rgba(168,85,247,0.2); color: var(--purple); border: 1px solid var(--purple); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
  .card-title { font-size: 0.85rem; color: var(--text-dim); text-transform: uppercase; margin-bottom: 8px; font-weight: 600; }
  .card-value { font-size: 1.8rem; font-weight: bold; }
  .bar-bg { background: #1e293b; height: 10px; border-radius: 5px; margin-top: 10px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); width: 0%; transition: width 0.2s ease; }
  .bar-fill.warning { background: var(--yellow); }
  .bar-fill.danger { background: var(--red); }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  td, th { padding: 8px 0; border-bottom: 1px solid var(--border); text-align: left; font-size: 0.95rem; }
  td:last-child { text-align: right; font-weight: bold; }
  .footer { text-align: center; color: var(--text-dim); font-size: 0.8rem; margin-top: 32px; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>AQUAPHY — Physical Safety Interlock</h1>
      <div style="color:var(--text-dim); font-size:0.85rem; margin-top:4px;">Bump-in-the-Wire Actuator Verification for Legacy Water OT</div>
    </div>
    <div id="state-badge" class="badge badge-NORMAL">NORMAL</div>
  </header>

  <div class="grid">
    <div class="card">
      <div class="card-title">Requested Dosing (u_req)</div>
      <div id="u-req" class="card-value">40.0%</div>
      <div class="bar-bg"><div id="u-req-bar" class="bar-fill" style="width:40%"></div></div>
    </div>
    <div class="card">
      <div class="card-title">Safe Forwarded Dosing (u_safe)</div>
      <div id="u-safe" class="card-value">40.0%</div>
      <div class="bar-bg"><div id="u-safe-bar" class="bar-fill" style="width:40%"></div></div>
    </div>
    <div class="card">
      <div class="card-title">Effluent Concentration (C)</div>
      <div id="conc" class="card-value">2.00 <span style="font-size:1rem;font-weight:normal;color:var(--text-dim)">mg/L</span></div>
      <div style="color:var(--text-dim);font-size:0.8rem;margin-top:6px;">Target: 2.00 | Safety Ceiling: 4.00</div>
    </div>
  </div>

  <div class="card" style="margin-bottom:24px;">
    <div class="card-title">Cumulative Excess Chemical Mass Tracker</div>
    <div style="display:flex; justify-content:space-between; align-items:baseline;">
      <div id="mass-text" style="font-size:1.4rem; font-weight:bold;">0.0 mg / 500.0 mg</div>
      <div id="budget-percent" style="color:var(--text-dim); font-size:0.9rem;">0.0% of budget</div>
    </div>
    <div class="bar-bg"><div id="mass-bar" class="bar-fill" style="width:0%"></div></div>
  </div>

  <div class="card">
    <div class="card-title">Physical Telemetry & Invariants</div>
    <table>
      <tr><td>Raw Water Volumetric Flow (Q)</td><td id="flow-val">10.0 L/s</td></tr>
      <tr><td>Physics-Derived Nominal Baseline (u_nom)</td><td id="nom-val">40.0%</td></tr>
      <tr><td>Dynamic Instantaneous Ceiling (u_max_inst)</td><td id="ceil-val">100.0%</td></tr>
      <tr><td>Interlock Action</td><td id="action-val" style="color:var(--green)">PASS</td></tr>
    </table>
  </div>

  <div class="footer">CyberCity Hackathon — Track A: Resilience Under Attack</div>
</div>

<script>
async function update() {
  try {
    const res = await fetch('/api/telemetry');
    const d = await res.json();
    document.getElementById('u-req').innerText = (d.u_req * 100).toFixed(1) + '%';
    document.getElementById('u-req-bar').style.width = Math.min(100, d.u_req * 100) + '%';

    document.getElementById('u-safe').innerText = (d.u_safe * 100).toFixed(1) + '%';
    document.getElementById('u-safe-bar').style.width = Math.min(100, d.u_safe * 100) + '%';

    document.getElementById('conc').innerHTML = d.concentration.toFixed(2) + ' <span style="font-size:1rem;font-weight:normal;color:var(--text-dim)">mg/L</span>';
    document.getElementById('flow-val').innerText = d.flow.toFixed(1) + ' L/s';
    document.getElementById('nom-val').innerText = (d.u_nom * 100).toFixed(1) + '%';
    document.getElementById('ceil-val').innerText = (d.u_max_inst * 100).toFixed(1) + '%';

    const mRatio = Math.min(1.0, d.m_excess / d.m_budget);
    document.getElementById('mass-text').innerText = d.m_excess.toFixed(1) + ' mg / ' + d.m_budget.toFixed(1) + ' mg';
    document.getElementById('budget-percent').innerText = (mRatio * 100).toFixed(1) + '% of budget';
    const mBar = document.getElementById('mass-bar');
    mBar.style.width = (mRatio * 100) + '%';
    if (mRatio > 0.9) { mBar.className = 'bar-fill danger'; }
    else if (mRatio > 0.5) { mBar.className = 'bar-fill warning'; }
    else { mBar.className = 'bar-fill'; }

    const badge = document.getElementById('state-badge');
    badge.className = 'badge badge-' + d.state;
    badge.innerText = d.state.replace('_', ' ');

    const actionVal = document.getElementById('action-val');
    if (Math.abs(d.u_req - d.u_safe) > 0.001) {
      actionVal.innerText = 'CLAMPED TO SAFE BOUNDARY';
      actionVal.style.color = 'var(--red)';
    } else {
      actionVal.innerText = 'PASS (VERIFIED SAFE)';
      actionVal.style.color = 'var(--green)';
    }
  } catch (e) {}
}
setInterval(update, 200);
update();
</script>
</body>
</html>
"""

    def start(self) -> None:
        """Start the HTTP dashboard server in a daemon thread."""
        provider = self.telemetry_provider
        html_page = self._build_html().encode("utf-8")

        class RequestHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress console logging for clean CLI output

            def do_GET(self) -> None:
                if self.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html_page)))
                    self.end_headers()
                    self.wfile.write(html_page)
                elif self.path == "/api/telemetry":
                    data = provider()
                    body = json.dumps(data).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        class ReusableServer(socketserver.TCPServer):
            allow_reuse_address = True

        self._server = ReusableServer((self.host, self.port), RequestHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the HTTP dashboard server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None
