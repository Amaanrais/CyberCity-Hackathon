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
from typing import Any, Dict

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

    def _get_current_telemetry(self) -> Dict[str, Any]:
        """Aggregate telemetry from proxy and PLC for dashboard rendering."""
        eval_res = self.proxy.latest_result
        if eval_res:
            return {
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
            q = self.plc.get_flow_rate()
            c = self.plc.get_concentration()
            u_nom = (q * 2.0 + 0.01 * 1000.0 * 2.0) / 100.0
            return {
                "u_req": self.plc.get_pump_setpoint(),
                "u_safe": self.plc.get_pump_setpoint(),
                "flow": q,
                "concentration": c,
                "u_max_inst": 0.80,
                "u_nom": u_nom,
                "m_excess": 0.0,
                "m_budget": 75.0,
                "state": self.proxy.current_state.value,
            }

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

    def run_scenario(self) -> bool:
        """Execute the deterministic five-phase resilience demo."""
        try:
            # =================================================================
            # Phase 0: Normal Baseline Operation
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 0: Normal Operating Baseline (Equilibrium Verification)")
            print("=" * 70)
            print("Plant operating at nominal conditions: Flow Q = 10 L/s, u = 40%, Target C = 2.00 mg/L")

            for _ in range(4):
                send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
                self.print_status("Phase 0: Nominal steady state")
                self.sleep(0.5)

            # =================================================================
            # Phase 1: Attack 1 — Acute Setpoint Spike
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 1: Threat Scenario 1 — Acute Setpoint Jump (Spike to 100%)")
            print("=" * 70)
            print("Adversary writes FC06 Register 0 = 1000 (100% pump stroke).")
            print("Instantaneous Safety Envelope calculates maximum permissible u_max.")

            acute_clamped = False
            for i in range(4):
                send_modbus_setpoint(port=self.proxy_port, u_command=1.00, trans_id=1100 + i)
                self.print_status(f"Phase 1 [Attack 1 Step {i+1}]: Attacker demands 100% -> Clamped to ceiling")
                self.sleep(0.3)
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

            # Simulate flow surge in PLC
            self.plc.set_flow_rate(18.0)
            self.sleep(0.2)

            for i in range(6):
                # Legitimate demand dosing for Q=18: u_nom = (18*2 + 0.01*1000*2)/100 = 0.56
                send_modbus_setpoint(port=self.proxy_port, u_command=0.56, trans_id=1200 + i)
                self.print_status(f"Phase 2 [Surge Step {i+1}]: Q=18 L/s, Dosing=56% -> Legitimately PASSED")
                self.sleep(0.4)

            telem = self._get_current_telemetry()
            assert telem["state"] == "NORMAL", f"Expected NORMAL during legitimate surge, got {telem['state']}"
            assert abs(telem["u_safe"] - 0.56) < 0.01, "Legitimate surge command was wrongly clamped!"
            print("[✓] RESULT: Dynamic flow invariant verified. The flow-aware physics baseline accepted the synthetic operational flow surge without triggering the interlock.")

            # Return flow to nominal
            self.plc.set_flow_rate(10.0)
            send_modbus_setpoint(port=self.proxy_port, u_command=0.40)
            self.sleep(1.0)

            # =================================================================
            # Phase 3: Attack 2 — Low-and-Slow Creeping Ramp
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 3: Threat Scenario 2 — Low-and-Slow Creep (Cumulative Drift)")
            print("=" * 70)
            print("Adversary increases dosing in small increments (u = 55%, nominal is 40%).")
            print("Individually BELOW instantaneous ceiling (80%), but secretly draining mass budget (75 mg).")

            clamped_observed = False
            step = 0
            while not clamped_observed and step < 40:
                step += 1
                send_modbus_setpoint(port=self.proxy_port, u_command=0.55, trans_id=1300 + step)
                self.print_status(f"Phase 3 [Attack 2 Step {step}]: Creeping u=55% (accumulating excess mg)")
                self.sleep(0.25)

                cur_state = self.proxy.current_state
                if cur_state == DefenseState.CLAMPED_CUMULATIVE:
                    clamped_observed = True
                    break

            telem = self._get_current_telemetry()
            assert clamped_observed or telem["state"] == "CLAMPED_CUMULATIVE", f"Expected CLAMPED_CUMULATIVE, got {telem['state']}"
            assert abs(telem["u_safe"] - 0.40) < 0.02, f"Expected safe clamped to nominal 0.40, got {telem['u_safe']}"
            print("[✓] RESULT: Cumulative drift budget exhausted. Interlock CLAMPED setpoint to nominal baseline.")

            # =================================================================
            # Phase 4: Failsafe Demonstration
            # =================================================================
            print("\n" + "=" * 70)
            print("PHASE 4: Failsafe Demonstration (Loss of Downstream PLC)")
            print("=" * 70)
            print("Simulating network failure / PLC crash...")

            # Abruptly shut down PLC
            self.plc.stop()
            self.sleep(0.3)

            # Issue write to proxy
            ok, returned_u, err = send_modbus_setpoint(port=self.proxy_port, u_command=0.70)
            self.print_status(f"Phase 4 [Failsafe]: Downstream lost -> Proxy enters FAILSAFE_HOLD")

            assert self.proxy.current_state == DefenseState.FAILSAFE_HOLD
            print(f"[✓] RESULT: Proxy detected communication loss. State = FAILSAFE_HOLD, holding last safe setpoint ({self.proxy.last_safe_u*100:.1f}%).")

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
    parser.add_argument("--no-web", action="store_true", help="Disable web dashboard server")
    parser.add_argument("--interactive", action="store_true", help="Enable clear-screen live ANSI console")
    parser.add_argument("--speed", type=float, default=2.0, help="Simulation speed multiplier (default 2.0x)")
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
        success = orchestrator.run_scenario()
        if not success:
            sys.exit(1)
    finally:
        orchestrator.stop()


if __name__ == "__main__":
    main()
