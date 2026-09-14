"""AquaPhy Operator Telemetry Dashboard (Phase 6).

Provides:
1. TerminalDashboard: ANSI-colored, real-time live console view.
2. DashboardServer: Lightweight local HTTP/JSON/SSE server for browser monitoring.
"""

from __future__ import annotations
import http.server
import json
from pathlib import Path
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
        run_demo_handler: Optional[Callable[[], Any]] = None,
        reset_demo_handler: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.telemetry_provider = telemetry_provider
        self.host = host
        self.port = port
        self.run_demo_handler = run_demo_handler
        self.reset_demo_handler = reset_demo_handler
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def _build_html(self) -> str:
        return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AQUAPHY — Cyber-Physical Water Safety</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #f8fafc;
    --card: #ffffff;
    --border: #e2e8f0;
    --border-subtle: #edf2f7;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    
    --teal: #0f766e;
    --teal-hover: #115e59;
    --teal-light: #f0fdfa;

    --green: #16a34a;
    --green-bg: #f0fdf4;
    --green-text: #15803d;
    --green-border: #bbf7d0;

    --red: #dc2626;
    --red-bg: #fef2f2;
    --red-text: #b91c1c;
    --red-border: #fecaca;

    --amber: #d97706;
    --amber-bg: #fffbeb;
    --amber-text: #b45309;
    --amber-border: #fde68a;

    --purple: #7c3aed;
    --purple-bg: #faf5ff;
    --purple-text: #6d28d9;
    --purple-border: #e9d5ff;

    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
    --shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.04), 0 2px 4px -2px rgba(15, 23, 42, 0.02);
    --shadow-md: 0 10px 25px -4px rgba(15, 23, 42, 0.06), 0 4px 6px -2px rgba(15, 23, 42, 0.02);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 32px 20px;
    -webkit-font-smoothing: antialiased;
  }

  .container {
    max-width: 920px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* Header */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    padding: 4px 2px 8px 2px;
  }
  .system-tag {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--teal);
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .title-group {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .main-title {
    font-size: 1.6rem;
    font-weight: 800;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }
  .subtitle-divider {
    color: var(--border);
    font-weight: 300;
    font-size: 1.2rem;
  }
  .subtitle {
    font-size: 0.95rem;
    color: var(--text-secondary);
    font-weight: 500;
  }
  .defense-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    background: var(--green-bg);
    color: var(--green-text);
    border: 1px solid var(--green-border);
  }
  .pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: soft-pulse 2s infinite ease-in-out;
  }
  @keyframes soft-pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.4; transform: scale(0.85); }
  }

  /* Status Bar */
  .status-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 14px 20px;
    box-shadow: var(--shadow);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
  }
  .status-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .status-label {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    text-transform: uppercase;
  }
  .status-val {
    font-size: 1rem;
    font-weight: 700;
    color: var(--text-primary);
  }
  .status-actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .btn {
    font-family: inherit;
    font-size: 0.82rem;
    font-weight: 600;
    padding: 8px 18px;
    border-radius: 9px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
    border: 1px solid transparent;
  }
  .btn:active { transform: translateY(1px); }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }
  .btn-primary {
    background: var(--teal);
    color: #ffffff;
  }
  .btn-primary:hover:not(:disabled) {
    background: var(--teal-hover);
  }
  .btn-secondary {
    background: #ffffff;
    color: var(--text-secondary);
    border-color: var(--border);
  }
  .btn-secondary:hover:not(:disabled) {
    background: #f8fafc;
    color: var(--text-primary);
    border-color: #cbd5e1;
  }

  /* Main Card: Pipeline */
  .main-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 32px 28px;
    box-shadow: var(--shadow);
  }
  .pipeline-grid {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .pipe-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }
  .col-title {
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 2px;
  }
  .col-sub {
    font-size: 0.74rem;
    color: var(--text-secondary);
    margin-bottom: 12px;
  }
  .pipe-num {
    font-size: 3.2rem;
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.03em;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
  }
  .num-req-normal { color: var(--text-primary); }
  .num-req-attack { color: var(--red); }
  .num-req-warning { color: var(--amber); }
  .num-safe { color: var(--green); }

  .pipe-subtext {
    font-size: 0.76rem;
    font-weight: 500;
    color: var(--text-muted);
    margin-top: 10px;
  }

  .pipe-arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    color: #cbd5e1;
    font-size: 1.8rem;
    user-select: none;
    padding-bottom: 16px;
  }

  .decision-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
  }
  .decision-pill {
    padding: 10px 24px;
    border-radius: 10px;
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    display: inline-block;
  }
  .pill-pass {
    background: var(--green-bg);
    color: var(--green-text);
    border: 1px solid var(--green-border);
  }
  .pill-clamped {
    background: var(--red-bg);
    color: var(--red-text);
    border: 1px solid var(--red-border);
  }
  .pill-hold {
    background: var(--purple-bg);
    color: var(--purple-text);
    border: 1px solid var(--purple-border);
  }

  /* Small Metrics Row */
  .metrics-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }
  .metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    box-shadow: var(--shadow);
  }
  .metric-label {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 8px;
  }
  .metric-value-row {
    display: flex;
    align-items: baseline;
    gap: 5px;
    margin-bottom: 4px;
  }
  .metric-val {
    font-size: 1.8rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--text-primary);
  }
  .metric-unit {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .metric-desc {
    font-size: 0.74rem;
    color: var(--text-muted);
  }

  /* Cumulative Excess Mass */
  .mass-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 24px;
    box-shadow: var(--shadow);
    transition: all 0.3s ease;
  }
  .mass-card.breached {
    border-color: var(--red-border);
    background: #fffafa;
  }
  .mass-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 12px;
  }
  .mass-title-group {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .card-title {
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    text-transform: uppercase;
  }
  .mass-numbers {
    font-size: 1.15rem;
    font-weight: 800;
    color: var(--text-primary);
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
  }
  .mass-numbers .unit {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .mass-bar-track {
    width: 100%;
    height: 12px;
    background: #f1f5f9;
    border-radius: 999px;
    overflow: hidden;
    border: 1px solid var(--border-subtle);
  }
  .mass-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.25s ease, background-color 0.25s ease;
  }
  .fill-normal { background: var(--teal); }
  .fill-warning { background: var(--amber); }
  .fill-danger { background: var(--red); }

  .mass-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 8px;
    font-size: 0.74rem;
    color: var(--text-muted);
  }
  .mass-card.breached .mass-footer {
    color: var(--red-text);
    font-weight: 600;
  }

  /* Current Event */
  .event-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px 24px;
    box-shadow: var(--shadow);
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .event-tag-wrap {
    min-width: 150px;
  }
  .event-pill {
    display: inline-block;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    text-align: center;
    width: 100%;
  }
  .event-pill-normal { background: var(--green-bg); color: var(--green-text); border: 1px solid var(--green-border); }
  .event-pill-danger { background: var(--red-bg); color: var(--red-text); border: 1px solid var(--red-border); }
  .event-pill-warning { background: var(--amber-bg); color: var(--amber-text); border: 1px solid var(--amber-border); }
  .event-pill-purple { background: var(--purple-bg); color: var(--purple-text); border: 1px solid var(--purple-border); }

  .event-text {
    font-size: 0.92rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.4;
  }

  @media (max-width: 720px) {
    .metrics-row { grid-template-columns: 1fr; }
    .pipeline-grid { flex-direction: column; }
    .pipe-arrow { transform: rotate(90deg); padding: 4px 0; }
    .event-card { flex-direction: column; align-items: flex-start; }
    .event-tag-wrap { min-width: auto; }
  }
</style>
</head>
<body>
<div class="container">

  <!-- TOP HEADER -->
  <header class="header">
    <div class="header-left">
      <div class="system-tag">SYNTHETIC WATER PROCESS — HACKATHON SIMULATION</div>
      <div class="title-group">
        <h1 class="main-title">AQUAPHY</h1>
        <span class="subtitle-divider">/</span>
        <span class="subtitle">Cyber-Physical Water Safety</span>
      </div>
    </div>
    <div class="header-right">
      <div class="defense-badge">
        <span class="pulse-dot"></span>
        DEFENSE ACTIVE
      </div>
    </div>
  </header>

  <!-- DEMO STATUS & CONTROLS -->
  <div class="status-card">
    <div class="status-info">
      <span class="status-label">DEMO STATUS</span>
      <span id="demo-status-text" class="status-val">READY FOR DEMONSTRATION</span>
    </div>
    <div class="status-actions">
      <button id="btn-run-demo" class="btn btn-primary" onclick="triggerRunDemo()">
        <span>▶</span> RUN LIVE DEMO
      </button>
      <button id="btn-reset-plant" class="btn btn-secondary" onclick="triggerResetPlant()">
        <span>↻</span> RESET
      </button>
    </div>
  </div>

  <!-- MAIN CARD: REQUESTED -> AQUAPHY -> SAFE / PLC -->
  <div class="main-card">
    <div class="pipeline-grid">
      
      <!-- Requested -->
      <div class="pipe-col">
        <div class="col-title">REQUESTED</div>
        <div class="col-sub">Attacker / SCADA Setpoint</div>
        <div id="u-req-val" class="pipe-num num-req-normal">40%</div>
        <div class="pipe-subtext">Chemical Pump Command</div>
      </div>

      <!-- Arrow 1 -->
      <div class="pipe-arrow">→</div>

      <!-- AquaPhy Decision -->
      <div class="pipe-col">
        <div class="col-title">AQUAPHY</div>
        <div class="col-sub">Inline Physical Interlock</div>
        <div class="decision-box">
          <div id="pipe-decision-badge" class="decision-pill pill-pass">PASS</div>
          <div id="pipe-decision-sub" class="pipe-subtext">Within Physical Invariant</div>
        </div>
      </div>

      <!-- Arrow 2 -->
      <div class="pipe-arrow">→</div>

      <!-- Safe / PLC -->
      <div class="pipe-col">
        <div class="col-title">SAFE / PLC</div>
        <div class="col-sub">Actual Enforced Actuation</div>
        <div id="u-safe-val" class="pipe-num num-safe">40%</div>
        <div class="pipe-subtext">Disinfection Pump Stroke</div>
      </div>

    </div>
  </div>

  <!-- SMALL METRICS ROW -->
  <div class="metrics-row">
    <div class="metric-card">
      <div class="metric-label">FLOW</div>
      <div class="metric-value-row">
        <span id="flow-val" class="metric-val">10.0</span>
        <span class="metric-unit">L/s</span>
      </div>
      <div class="metric-desc">Raw water inflow rate (Q)</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">CONCENTRATION</div>
      <div class="metric-value-row">
        <span id="conc-val" class="metric-val">2.00</span>
        <span class="metric-unit">mg/L</span>
      </div>
      <div class="metric-desc">Effluent disinfectant (C) | Target: 2.00</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">SAFE LIMIT</div>
      <div class="metric-value-row">
        <span id="limit-val" class="metric-val">80%</span>
      </div>
      <div class="metric-desc">Instantaneous safety ceiling (u_max)</div>
    </div>
  </div>

  <!-- CUMULATIVE EXCESS MASS -->
  <div id="mass-card" class="mass-card">
    <div class="mass-header">
      <div class="mass-title-group">
        <span class="card-title">CUMULATIVE EXCESS MASS</span>
      </div>
      <div class="mass-numbers">
        <span id="mass-curr">0.0</span> / <span id="mass-budget">75.0</span> <span class="unit">mg</span>
      </div>
    </div>
    <div class="mass-bar-track">
      <div id="mass-bar-fill" class="mass-bar-fill fill-normal" style="width: 0%;"></div>
    </div>
    <div class="mass-footer">
      <span id="mass-footer-note">Budget intact (sliding 60s window)</span>
      <span id="mass-pct-pill">0.0% of budget</span>
    </div>
  </div>

  <!-- CURRENT EVENT -->
  <div class="event-card">
    <div class="event-tag-wrap">
      <span id="event-state-badge" class="event-pill event-pill-normal">NORMAL</span>
    </div>
    <div id="event-message" class="event-text">
      Ready for demonstration. Command is within the physical safety envelope.
    </div>
  </div>

</div>

<script>
function triggerRunDemo() {
  const btn = document.getElementById('btn-run-demo');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> RUNNING...';
  }
  fetch('/api/demo/run', { method: 'POST' })
    .then(r => r.json())
    .then(() => setTimeout(update, 100))
    .catch(e => console.error(e));
}

function triggerResetPlant() {
  const btn = document.getElementById('btn-reset-plant');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> RESETTING...';
  }
  fetch('/api/demo/reset', { method: 'POST' })
    .then(r => r.json())
    .then(() => setTimeout(update, 100))
    .catch(e => console.error(e));
}

async function update() {
  try {
    const res = await fetch('/api/telemetry');
    const d = await res.json();

    const uReqPct = Math.round(d.u_req * 100);
    const uSafePct = Math.round(d.u_safe * 100);
    const uCeilPct = Math.round((d.u_max_inst !== undefined ? d.u_max_inst : 0.8) * 100);
    const isSurge = d.flow >= 14.0;
    const mBudget = (d.m_budget !== undefined ? d.m_budget : 75.0);
    const mExcess = (d.m_excess !== undefined ? d.m_excess : 0.0);
    const massRatio = Math.min(1.0, mExcess / (mBudget > 0 ? mBudget : 75.0));
    const demoStatus = d.demo_status || 'IDLE';

    // 1. Controls & Top Status
    const btnRun = document.getElementById('btn-run-demo');
    const btnReset = document.getElementById('btn-reset-plant');
    const statusText = document.getElementById('demo-status-text');

    if (demoStatus === 'RUNNING') {
      if (btnRun) {
        btnRun.disabled = true;
        btnRun.innerHTML = '<span>⏳</span> RUNNING...';
        btnRun.className = 'btn btn-secondary';
      }
      if (btnReset) btnReset.disabled = true;
      if (statusText) statusText.innerText = d.phase_title ? d.phase_title : 'DEMO IN PROGRESS';
    } else if (demoStatus === 'COMPLETE') {
      if (btnRun) {
        btnRun.disabled = true;
        btnRun.innerHTML = '<span>✓</span> COMPLETED';
        btnRun.className = 'btn btn-secondary';
      }
      if (btnReset) {
        btnReset.disabled = false;
        btnReset.className = 'btn btn-primary';
      }
      if (statusText) statusText.innerText = 'DEMONSTRATION COMPLETE';
    } else {
      // IDLE / READY
      if (btnRun) {
        btnRun.disabled = false;
        btnRun.innerHTML = '<span>▶</span> RUN LIVE DEMO';
        btnRun.className = 'btn btn-primary';
      }
      if (btnReset) {
        btnReset.disabled = false;
        btnReset.className = 'btn btn-secondary';
      }
      if (statusText) statusText.innerText = 'READY FOR DEMONSTRATION';
    }

    // 2. Main Dominant Pipeline Card
    const elReq = document.getElementById('u-req-val');
    const elSafe = document.getElementById('u-safe-val');
    const elBadge = document.getElementById('pipe-decision-badge');
    const elSub = document.getElementById('pipe-decision-sub');

    elReq.innerText = `${uReqPct}%`;
    elSafe.innerText = `${uSafePct}%`;

    if (d.state === 'CLAMPED_INSTANTANEOUS') {
      elReq.className = 'pipe-num num-req-attack';
      elBadge.className = 'decision-pill pill-clamped';
      elBadge.innerText = 'CLAMPED';
      elSub.innerText = `Predictive ceiling (${uCeilPct}%) enforced`;
    } else if (d.state === 'CLAMPED_CUMULATIVE') {
      elReq.className = 'pipe-num num-req-warning';
      elBadge.className = 'decision-pill pill-clamped';
      elBadge.innerText = 'CLAMPED';
      elSub.innerText = 'Nominal baseline (40%) enforced';
    } else if (d.state === 'FAILSAFE_HOLD') {
      elReq.className = 'pipe-num num-req-normal';
      elBadge.className = 'decision-pill pill-hold';
      elBadge.innerText = 'HOLD';
      elSub.innerText = 'PLC communication lost';
    } else {
      elReq.className = 'pipe-num num-req-normal';
      elBadge.className = 'decision-pill pill-pass';
      elBadge.innerText = 'PASS';
      elSub.innerText = isSurge ? 'Legitimate surge accepted' : 'Within physical envelope';
    }

    // 3. Small Metrics Row
    document.getElementById('flow-val').innerText = d.flow.toFixed(1);
    document.getElementById('conc-val').innerText = d.concentration.toFixed(2);
    document.getElementById('limit-val').innerText = `${uCeilPct}%`;

    // 4. Cumulative Excess Mass
    const massCurr = document.getElementById('mass-curr');
    const massBudget = document.getElementById('mass-budget');
    const massBar = document.getElementById('mass-bar-fill');
    const massCard = document.getElementById('mass-card');
    const massNote = document.getElementById('mass-footer-note');
    const massPct = document.getElementById('mass-pct-pill');

    massCurr.innerText = mExcess.toFixed(1);
    massBudget.innerText = mBudget.toFixed(1);
    massBar.style.width = `${Math.round(massRatio * 100)}%`;
    massPct.innerText = `${(massRatio * 100).toFixed(0)}% of budget`;

    if (massRatio >= 1.0) {
      massBar.className = 'mass-bar-fill fill-danger';
      massCard.className = 'mass-card breached';
      massNote.innerText = `Limit exceeded (${mExcess.toFixed(1)} mg > ${mBudget.toFixed(1)} mg) — Clamping setpoint to 40%`;
    } else if (massRatio >= 0.70) {
      massBar.className = 'mass-bar-fill fill-warning';
      massCard.className = 'mass-card';
      massNote.innerText = `Approaching limit (${mExcess.toFixed(1)} mg / ${mBudget.toFixed(1)} mg)`;
    } else {
      massBar.className = 'mass-bar-fill fill-normal';
      massCard.className = 'mass-card';
      massNote.innerText = 'Budget intact (sliding 60s window)';
    }

    // 5. Current Event & State Presentation
    const eventBadge = document.getElementById('event-state-badge');
    const eventMsg = document.getElementById('event-message');

    if (d.state === 'CLAMPED_INSTANTANEOUS') {
      eventBadge.className = 'event-pill event-pill-danger';
      eventBadge.innerText = 'ATTACK BLOCKED';
      eventMsg.innerText = 'Requested dosing exceeded the predicted physical safety limit.';
    } else if (d.state === 'CLAMPED_CUMULATIVE') {
      eventBadge.className = 'event-pill event-pill-danger';
      eventBadge.innerText = 'CUMULATIVE LIMIT';
      eventMsg.innerText = 'Cumulative excess dosing limit exceeded.';
    } else if (d.state === 'FAILSAFE_HOLD') {
      eventBadge.className = 'event-pill event-pill-purple';
      eventBadge.innerText = 'FAILSAFE HOLD';
      eventMsg.innerText = 'PLC communication lost. Last known-safe setpoint is being held.';
    } else if (isSurge) {
      eventBadge.className = 'event-pill event-pill-normal';
      eventBadge.innerText = 'NORMAL';
      eventMsg.innerText = 'Flow increased, so the physics-derived dosing baseline adapted. LEGITIMATE SURGE ACCEPTED.';
    } else if (demoStatus === 'COMPLETE') {
      eventBadge.className = 'event-pill event-pill-purple';
      eventBadge.innerText = 'DEMO COMPLETE';
      eventMsg.innerText = 'All resilience scenarios verified. Last known-safe setpoint is being held.';
    } else if (demoStatus === 'IDLE') {
      eventBadge.className = 'event-pill event-pill-normal';
      eventBadge.innerText = 'NORMAL';
      eventMsg.innerText = 'Ready for demonstration. Command is within the physical safety envelope.';
    } else {
      eventBadge.className = 'event-pill event-pill-normal';
      eventBadge.innerText = 'NORMAL';
      eventMsg.innerText = 'Command is within the physical safety envelope.';
    }

  } catch (e) {}
}

setInterval(update, 150);
update();
</script>
</body>
</html>
"""

    def start(self) -> None:
        """Start the HTTP dashboard server in a daemon thread."""
        provider = self.telemetry_provider
        run_handler = self.run_demo_handler
        reset_handler = self.reset_demo_handler
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
                elif self.path == "/api/audit":
                    records = []
                    audit_file = Path("data/audit_log.jsonl")
                    if audit_file.exists():
                        try:
                            lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
                            for line in lines[-10:]:
                                if line.strip():
                                    records.append(json.loads(line))
                        except Exception:
                            pass
                    body = json.dumps(records).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/demo/run":
                    res = run_handler() if run_handler else {"status": "unsupported"}
                    body = json.dumps(res).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/demo/reset":
                    res = reset_handler() if reset_handler else {"status": "unsupported"}
                    body = json.dumps(res).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:
                if self.path == "/api/demo/run":
                    res = run_handler() if run_handler else {"status": "unsupported"}
                    body = json.dumps(res).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/demo/reset":
                    res = reset_handler() if reset_handler else {"status": "unsupported"}
                    body = json.dumps(res).encode("utf-8")
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
