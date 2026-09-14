#!/usr/bin/env python3
"""AquaPhy End-to-End Live Demonstration Orchestrator (Phase 7).

Coordinates:
    1. Synthetic Modbus TCP PLC (Port 5021) with integrated CSTR process physics
    2. AquaPhy Bump-in-the-Wire Modbus Proxy (Port 5020)
    3. Real-Time Telemetry Dashboard (Terminal UI + HTTP Server Port 8080)
    4. Deterministic Multi-Phase Attack & Resilience Scenarios:
       - Phase 0: Normal Steady State (u = 0.40, Q = 10.0, C = 2.0 mg/L)
       - Phase 1: Attack 1 — Acute Setpoint Spike (Instantaneous Clamping)
       - Phase 2: Operational Flow Surge (Dynamic Flow Invariant Verification)
       - Phase 3: Attack 2 — Low-and-Slow Creep (Cumulative Mass Budget Clamping)
       - Phase 4: Failsafe Demonstration (Downstream Fault Handling)

Usage:
    python3 demo/run_demo.py [--non-interactive] [--no-web] [--speed SPEED]
"""

from __future__ import annotations
import argparse
from pathlib import Path
import signal
import sys
import time
import threading
from typing import Any, Dict, Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.simulation.cstr import CSTRSimulation, CSTRParameters
from src.plc.synthetic_plc import SyntheticPLC, ModbusRegisters
from src.interlock.physics_engine import (
    PhysicsEngine,
    DefenseState,
    InterlockParameters,
)
from src.interlock.proxy import ModbusProxy
from src.ui.dashboard import TerminalDashboard, DashboardServer
from demo.attacker_scripts import send_modbus_setpoint, read_telemetry


# Accelerated cumulative mass budget for deterministic hackathon demonstration.
# The full engineering architecture specifies 500.0 mg (approx 50s at 10% sustained excess dosing);
# this accelerated value permits deterministic demonstration of cumulative clamping within ~15 seconds.
DEMO_ACCELERATED_MASS_BUDGET: float = 75.0


class AquaPhyDemoOrchestrator:
    """Manages the full lifecycle and scenario progression of the AquaPhy prototype."""

    def __init__(
        self,
        plc_port: int = 5021,
        proxy_port: int = 5020,
        web_port: int = 8080,
        enable_web: bool = True,
        interactive: bool = False,
        speed: float = 1.0,
        mass_budget: float = DEMO_ACCELERATED_MASS_BUDGET,
    ) -> None:
        self.plc_port = plc_port
        self.proxy_port = proxy_port
        self.web_port = web_port
        self.enable_web = enable_web
        self.interactive = interactive
        self.speed = max(0.1, float(speed))
        self.mass_budget = mass_budget

        self._lock = threading.Lock()
        self.demo_status: str = "IDLE"  # "IDLE", "RUNNING", "COMPLETE", "ERROR"
        self.current_phase_num: int = 0
        self.phase_title: str = "READY FOR DEMONSTRATION"
        self.phase_desc: str = "Plant operating at steady state: Q = 10.0 L/s, u = 40.0%, Target C = 2.00 mg/L."

        # Core components
        self.sim = CSTRSimulation()
        # Scale simulation time with demo speed multiplier so physical dynamics match presentation rate
        self.plc = SyntheticPLC(port=self.plc_port, sim=self.sim, auto_sim=True, time_scale=self.speed)

        # Tuned parameters for scientific demonstration:
        # - DEMO_ACCELERATED_MASS_BUDGET (75 mg demo profile; architectural baseline is 500 mg)
        # - Short-horizon predictive safety envelope horizon H = 50.0s (reactor residence time constant tau)
        interlock_params = InterlockParameters(
            mass_budget=self.mass_budget,
            window_duration=60.0,
            horizon=50.0,
        )
        self.engine = PhysicsEngine(params=interlock_params)
        self.proxy = ModbusProxy(
            listen_port=self.proxy_port,
            plc_port=self.plc_port,
            engine=self.engine,
            telemetry_poll_interval=0.05,
            time_scale=self.speed,
        )

        self.web_server: DashboardServer | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _get_current_telemetry(self) -> Dict[str, Any]:
        """Aggregate telemetry from proxy and PLC for dashboard rendering."""
        eval_res = self.proxy.latest_result
        if eval_res:
            telem = {
                "u_req": eval_res.u_req,
                "u_safe": eval_res.u_safe,
                "flow": eval_res.flow,
                "concentration": eval_res.concentration,
                "u_max_inst": eval_res.u_max_inst,
                "u_nom": eval_res.u_nom,
                "m_excess": eval_res.m_excess,
                "m_budget": eval_res.m_budget,
                "state": eval_res.decision.value,
            }
        else:
            try:
                q = self.plc.get_flow_rate()
                c = self.plc.get_concentration()
                u_curr = self.plc.get_pump_setpoint()
            except Exception:
                q, c, u_curr = 10.0, 2.0, 0.40
            u_nom = (q * 2.0 + 0.01 * 1000.0 * 2.0) / 100.0
            telem = {
                "u_req": u_curr,
                "u_safe": u_curr,
                "flow": q,
                "concentration": c,
                "u_max_inst": 0.80,
                "u_nom": u_nom,
                "m_excess": 0.0,
                "m_budget": self.mass_budget,
                "state": self.proxy.current_state.value,
            }

        with self._lock:
            telem["demo_status"] = self.demo_status
            telem["phase_num"] = self.current_phase_num
            telem["phase_title"] = self.phase_title
            telem["phase_desc"] = self.phase_desc
        return telem

    def print_status(self, message: str = "") -> None:
        """Display current system status frame."""
        telem = self._get_current_telemetry()
        if self.interactive:
            print(TerminalDashboard.CLEAR_SCREEN)
            print(TerminalDashboard.format_frame(telem))
            if message:
                print(f"\n >>> {message}")
        else:
            state_str = telem["state"]
            u_req = telem["u_req"]
            u_safe = telem["u_safe"]
            c = telem["concentration"]
            q = telem["flow"]
            m_ex = telem["m_excess"]
            action = "CLAMPED" if abs(u_req - u_safe) > 0.001 else "PASS"
            print(f"[{state_str:20s}] Q={q:4.1f} L/s | C={c:4.2f} mg/L | Req={u_req*100:4.1f}% -> Safe={u_safe*100:4.1f}% ({action}) | M_ex={m_ex:4.1f}mg | {message}")

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds / self.speed)

    def start(self) -> None:
        """Boot all services cleanly."""
        print(f"[*] Starting AquaPhy Synthetic PLC on port {self.plc_port}...")
        self.plc.start()
        time.sleep(0.1)

        print(f"[*] Starting AquaPhy Inline Interlock Proxy on port {self.proxy_port} -> PLC port {self.plc_port}...")
        self.proxy.start()
        time.sleep(0.1)

        if self.enable_web:
            print(f"[*] Starting AquaPhy Web Dashboard on http://127.0.0.1:{self.web_port}...")
            self.web_server = DashboardServer(
                telemetry_provider=self._get_current_telemetry,
                port=self.web_port,
                run_demo_handler=self.start_demo_async,
                reset_demo_handler=self.reset_plant,
            )
            self.web_server.start()

        self._running = True
        print("[✓] All AquaPhy system services operational.\n")

    def stop(self) -> None:
        """Tear down all services cleanly without orphaned sockets."""
        print("\n[*] Shutting down AquaPhy demonstration services...")
        self._running = False
        if self.proxy:
            self.proxy.stop()
        if self.plc:
            self.plc.stop()
        if self.web_server:
            self.web_server.stop()
        print("[✓] Clean shutdown complete.")

    def start_demo_async(self) -> Dict[str, Any]:
        """Start the interactive demonstration scenario in a background thread."""
        with self._lock:
            if self.demo_status == "RUNNING":
                return {"status": "already_running", "message": "Demo is already in progress"}
            self.demo_status = "RUNNING"

        thread = threading.Thread(target=self._run_presentation_worker, daemon=True)
        thread.start()
        return {"status": "ok", "message": "Demo started"}

    def _run_presentation_worker(self) -> None:
        """Worker thread executing scenario in presentation mode."""
        try:
            success = self.run_scenario(presentation_mode=True)
            with self._lock:
                if success:
                    self.demo_status = "COMPLETE"
                    self.phase_title = "DEMONSTRATION COMPLETE"
                    self.phase_desc = "All 5 physical resilience scenarios demonstrated successfully."
                else:
                    self.demo_status = "ERROR"
                    self.phase_title = "DEMONSTRATION FAILED"
                    self.phase_desc = "An assertion failure occurred during scenario execution."
        except Exception as ex:
            with self._lock:
                self.demo_status = "ERROR"
                self.phase_title = "DEMONSTRATION ERROR"
                self.phase_desc = str(ex)

    def reset_plant(self) -> Dict[str, Any]:
        """Restore the complete demo state after Phase 4 or at any time.

        Guarantees:
        1. PLC is running on self.plc_port
        2. Proxy downstream connection is healthy
        3. Interlock cumulative history is cleared
        4. Defense state is NORMAL
        5. Flow Q = 10.0 L/s
        6. Pump setpoint = 40% (0.40)
        7. Effluent concentration returns toward ~2 mg/L
        8. Dashboard status says READY FOR DEMONSTRATION
        """
        print("\n[*] Resetting AquaPhy demonstration system to initial steady state...")
        with self._lock:
            # 1. Stop existing PLC cleanly if still running
            if self.plc:
                try:
                    self.plc.stop()
                except Exception:
                    pass

            # 2. Re-instantiate fresh CSTRSimulation and SyntheticPLC
            self.sim = CSTRSimulation()
            self.plc = SyntheticPLC(
                port=self.plc_port,
                sim=self.sim,
                auto_sim=True,
                time_scale=self.speed,
            )
            self.plc.start()
            time.sleep(0.15)

            # 3. Clear interlock engine cumulative history and state
            self.engine.reset()

            # 4. Restore proxy downstream state and healthy status
            with self.proxy._lock:
                self.proxy._cached_q = 10.0
                self.proxy._cached_c = 2.0
                self.proxy._state = DefenseState.NORMAL
                self.proxy._last_safe_u = 0.40
                self.proxy._downstream_healthy = True
                self.proxy._last_interlock_wall_time = time.monotonic()

            # 5. Set nominal pump command through proxy to verify proxy -> PLC path
            try:
                send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
            except Exception:
                pass

            # 6. Reset presentation metadata
            self.demo_status = "IDLE"
            self.current_phase_num = 0
            self.phase_title = "READY FOR DEMONSTRATION"
            self.phase_desc = "Plant operating at steady state: Q = 10.0 L/s, u = 40.0%, Target C = 2.00 mg/L."

        telem = self._get_current_telemetry()
        print("[✓] AquaPhy plant reset complete. System READY FOR DEMONSTRATION.\n")
        return telem

    def run_scenario(self, presentation_mode: bool = False) -> bool:
        """Execute the deterministic five-phase resilience demo.

        Args:
            presentation_mode: If True, uses presentation pacing designed for live
                               demonstrations and judge evaluation (observable dwell times,
                               observable cumulative mass climb ~50mg -> ~60mg -> ~70mg -> >75mg).
                               If False (default for tests/CLI), executes rapidly.
        """
        try:
            # =================================================================
            # Phase 0: Normal Baseline Operation
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 0: Normal Operating Baseline (Equilibrium Verification)")
            print("=" * 70)
            print("Plant operating at nominal conditions: Flow Q = 10 L/s, u = 40%, Target C = 2.00 mg/L")

            with self._lock:
                self.current_phase_num = 0
                self.phase_title = "PHASE 0: NOMINAL"
                self.phase_desc = "Normal Operating Baseline. Q = 10.0 L/s, u = 40.0%, Target C = 2.00 mg/L."

            p0_steps = 4
            p0_sleep = 0.50 if presentation_mode else 0.50
            for _ in range(p0_steps):
                send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
                self.print_status("Phase 0: Nominal steady state")
                self.sleep(p0_sleep)

            # =================================================================
            # Phase 1: Attack 1 — Acute Setpoint Spike
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 1: Threat Scenario 1 — Acute Setpoint Jump (Spike to 100%)")
            print("=" * 70)
            print("Adversary writes FC06 Register 0 = 1000 (100% pump stroke).")
            print("Instantaneous Safety Envelope calculates maximum permissible u_max.")

            with self._lock:
                self.current_phase_num = 1
                self.phase_title = "PHASE 1: ACUTE SPIKE"
                self.phase_desc = "Attack 1: Acute Setpoint Jump to 100%. Instantaneous predictive ceiling enforced."

            acute_clamped = False
            # 4 steps at 40 mg/s excess rate yields precisely ~50 mg baseline for Phase 3
            p1_steps = 4
            p1_sleep = 0.32
            for i in range(p1_steps):
                send_modbus_setpoint(port=self.proxy_port, u_command=1.00, trans_id=1100 + i)
                self.print_status(f"Phase 1 [Attack 1 Step {i+1}]: Attacker demands 100% -> Clamped to ceiling")
                self.sleep(p1_sleep)
                if self.proxy.current_state == DefenseState.CLAMPED_INSTANTANEOUS:
                    acute_clamped = True

            telem = self._get_current_telemetry()
            assert acute_clamped, f"Expected CLAMPED_INSTANTANEOUS, got {telem['state']}"
            assert telem["u_safe"] < 1.0, f"Expected clamped command, got {telem['u_safe']}"
            assert telem["concentration"] < 4.0, f"Concentration breached limit: {telem['concentration']}"
            print("[✓] RESULT: Acute attack deterministically CLAMPED. Water safety invariant preserved.")

            # Return to nominal for next phase
            send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
            self.sleep(1.0)

            # =================================================================
            # Phase 2: Legitimate Operational Flow Surge
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 2: Operational Flow Surge (Dynamic Flow Coupling Invariant)")
            print("=" * 70)
            print("Municipal morning peak: Raw water inflow increases from 10.0 L/s to 18.0 L/s.")
            print("Plant SCADA commands higher dosing (u = 56%) to maintain target disinfection.")

            with self._lock:
                self.current_phase_num = 2
                self.phase_title = "PHASE 2: FLOW SURGE"
                self.phase_desc = "Operational Flow Surge to 18 L/s. Flow-coupled physics baseline accepts legitimate dosing."

            # Simulate flow surge in PLC
            self.plc.set_flow_rate(18.0)
            self.sleep(0.2)

            p2_steps = 6
            p2_sleep = 0.35
            for i in range(p2_steps):
                # Legitimate demand dosing for Q=18: u_nom = (18*2 + 0.01*1000*2)/100 = 0.56
                send_modbus_setpoint(port=self.proxy_port, u_command=0.56, trans_id=1200 + i)
                self.print_status(f"Phase 2 [Surge Step {i+1}]: Q=18 L/s, Dosing=56% -> Legitimately PASSED")
                self.sleep(p2_sleep)

            telem = self._get_current_telemetry()
            assert telem["state"] == "NORMAL", f"Expected NORMAL during legitimate surge, got {telem['state']}"
            assert abs(telem["u_safe"] - 0.56) < 0.01, "Legitimate surge command was wrongly clamped!"
            print("[✓] RESULT: Dynamic flow invariant verified. The flow-aware physics baseline accepted the synthetic operational flow surge without triggering the interlock.")

            # Return dosing to nominal FIRST before restoring flow, preventing spurious excess accumulation
            send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
            self.sleep(0.2)
            self.plc.set_flow_rate(10.0)
            self.sleep(0.8 if presentation_mode else 0.5)

            # =================================================================
            # Phase 3: Attack 2 — Low-and-Slow Creeping Ramp
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 3: Threat Scenario 2 — Low-and-Slow Creep (Cumulative Drift)")
            print("=" * 70)
            print("Adversary increases dosing in small increments (u = 55%, nominal is 40%).")
            print("Individually BELOW instantaneous ceiling (80%), but secretly draining mass budget (75 mg).")

            with self._lock:
                self.current_phase_num = 3
                self.phase_title = "PHASE 3: STEALTH CREEP"
                self.phase_desc = f"Attack 2: Low-and-Slow Creep (u=55%). Mass budget draining toward {self.mass_budget:.1f} mg."

            clamped_observed = False
            step = 0
            max_steps = 80 if presentation_mode else 40
            sleep_interval = 0.30 if presentation_mode else 0.25

            # Reliably step until cumulative threshold is breached and clamped
            # Visual progression: ~50 mg -> ~60 mg -> ~70 mg -> >75 mg
            while not clamped_observed and step < max_steps:
                step += 1
                send_modbus_setpoint(port=self.proxy_port, u_command=0.55, trans_id=1300 + step)
                self.sleep(sleep_interval)
                cur_telem = self._get_current_telemetry()
                m_curr = cur_telem.get("m_excess", 0.0)
                cur_state = self.proxy.current_state

                self.print_status(f"Phase 3 [Attack 2 Step {step}]: Creeping u=55% (M_excess={m_curr:4.1f} mg / {self.mass_budget:.1f} mg)")

                if cur_state == DefenseState.CLAMPED_CUMULATIVE or m_curr >= self.mass_budget:
                    clamped_observed = True
                    break

            telem = self._get_current_telemetry()
            assert clamped_observed or telem["state"] == "CLAMPED_CUMULATIVE", f"Expected CLAMPED_CUMULATIVE, got {telem['state']}"
            assert abs(telem["u_safe"] - 0.40) < 0.02, f"Expected safe clamped to nominal 0.40, got {telem['u_safe']}"
            print("[✓] RESULT: Cumulative drift budget exhausted. Interlock CLAMPED setpoint to nominal baseline.")

            # In presentation mode, provide observable dwell in clamped state (~4.5-5.0s)
            # so evaluators clearly observe: ~50mg -> ~60mg -> ~70mg -> >75mg -> CLAMPED TO 40%
            # Total Phase 3 presentation time: ~6.5 - 7.5 seconds
            if presentation_mode:
                with self._lock:
                    self.phase_title = "PHASE 3: STEALTH CREEP CLAMPED"
                    self.phase_desc = f"Cumulative excess mass ({telem['m_excess']:.1f} mg) exceeded budget ({self.mass_budget:.1f} mg). CLAMPED TO 40%."
                for dwell_i in range(14):
                    send_modbus_setpoint(port=self.proxy_port, u_command=0.55, trans_id=1350 + dwell_i)
                    self.sleep(0.35)
                    cur_telem = self._get_current_telemetry()
                    self.print_status(f"Phase 3 [Clamped Dwell {dwell_i+1}/14]: Adversary commands 55% -> Interlock enforces 40% clamp (M_excess={cur_telem['m_excess']:.1f} mg)")

            # =================================================================
            # Phase 4: Failsafe Demonstration
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 4: Failsafe Demonstration (Loss of Downstream PLC)")
            print("=" * 70)
            print("Simulating network failure / PLC crash...")

            with self._lock:
                self.current_phase_num = 4
                self.phase_title = "PHASE 4: FAILSAFE"
                self.phase_desc = "Downstream PLC link lost. Interlock proxy entered FAILSAFE_HOLD."

            # Abruptly shut down PLC
            self.plc.stop()
            self.sleep(0.4 if presentation_mode else 0.3)

            # Issue write to proxy
            ok, returned_u, err = send_modbus_setpoint(port=self.proxy_port, u_command=0.70)
            self.print_status(f"Phase 4 [Failsafe]: Downstream lost -> Proxy enters FAILSAFE_HOLD")

            assert self.proxy.current_state == DefenseState.FAILSAFE_HOLD
            print(f"[✓] RESULT: Proxy detected communication loss. State = FAILSAFE_HOLD, holding last safe setpoint ({self.proxy.last_safe_u*100:.1f}%).")

            if presentation_mode:
                for hold_i in range(6):
                    self.sleep(0.5)
                    self.print_status(f"Phase 4 [Failsafe Hold {hold_i+1}/6]: System securely locked in FAILSAFE_HOLD")

            print("\n" + "=" * 70)
            print("ALL AQUAPHY DEMONSTRATION PHASES COMPLETED SUCCESSFULLY")
            print("=" * 70)
            return True

        except AssertionError as err:
            print(f"\n[!] DEMO ASSERTION FAILED: {err}")
            return False
        except Exception as ex:
            print(f"\n[!] UNEXPECTED DEMO ERROR: {ex}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description="AquaPhy Live Demonstration Runner")
    parser.add_argument("--plc-port", type=int, default=5021, help="Synthetic PLC Modbus port")
    parser.add_argument("--proxy-port", type=int, default=5020, help="AquaPhy Interlock Proxy port")
    parser.add_argument("--web-port", type=int, default=8080, help="Web Dashboard HTTP port")
    parser.add_argument("--no-web", action="store_true", help="Disable web dashboard server and run CLI scenario directly")
    parser.add_argument("--interactive", action="store_true", help="Enable clear-screen live ANSI console")
    parser.add_argument("--speed", type=float, default=1.0, help="Simulation speed multiplier (default 1.0x process time)")
    parser.add_argument("--auto-run", action="store_true", help="Automatically trigger demo scenario after starting")
    args = parser.parse_args()

    orchestrator = AquaPhyDemoOrchestrator(
        plc_port=args.plc_port,
        proxy_port=args.proxy_port,
        web_port=args.web_port,
        enable_web=not args.no_web,
        interactive=args.interactive,
        speed=args.speed,
    )

    def sigint_handler(sig: Any, frame: Any) -> None:
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigint_handler)

    try:
        orchestrator.start()

        if args.no_web:
            # Traditional CLI execution: run scenario directly and exit
            success = orchestrator.run_scenario(presentation_mode=False)
            if not success:
                sys.exit(1)
            return

        # Web presentation mode
        print("=" * 72)
        print("     AQUAPHY INTERACTIVE PRESENTATION SERVER READY ON PORT " + str(args.web_port))
        print("=" * 72)
        print(f" Web Console : http://127.0.0.1:{args.web_port}")
        print(" Plant Status: READY FOR DEMONSTRATION (Phase 0 Nominal Baseline)")
        print(" Web Controls: Click [ RUN LIVE DEMO ] in the web dashboard")
        print(" CLI Commands: Press [ENTER] to run, type 'reset' to restore, Ctrl+C to quit")
        print("=" * 72 + "\n")

        if args.auto_run:
            orchestrator.start_demo_async()

        # Non-blocking interactive loop for terminal while web server is active
        while orchestrator.is_running:
            if sys.stdin.isatty():
                try:
                    user_input = input().strip().lower()
                    if user_input in ("q", "quit", "exit"):
                        break
                    elif user_input in ("r", "reset"):
                        orchestrator.reset_plant()
                    elif user_input in ("", "run", "start"):
                        if orchestrator.demo_status == "COMPLETE":
                            print("[*] Demonstration already completed. Resetting plant first...")
                            orchestrator.reset_plant()
                            time.sleep(0.5)
                        orchestrator.start_demo_async()
                except (EOFError, KeyboardInterrupt):
                    break
            else:
                time.sleep(0.5)

    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
