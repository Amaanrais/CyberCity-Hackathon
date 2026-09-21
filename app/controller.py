import asyncio
import datetime
import sys
import time
from typing import Optional

from app.audit import AuditSink
from app.interlock import SafetyInterlock
from app.models import DecisionRecord, DecisionType, EventType
from app.plant import PlantSimulator
from app.state import SystemStateManager


class PlantController:
    """
    Main 1-second SCADA control loop.
    Reads sensor feedback, calculates requested pump dosing, passes commands
    through the Safety Instrumented System (SIS) interlock, actuates the simulated
    metering pump, and logs decisions to the in-memory cache and background SQLite sink.
    """

    def __init__(
        self,
        plant_sim: PlantSimulator,
        interlock: SafetyInterlock,
        state_mgr: SystemStateManager,
        audit_sink: AuditSink
    ):
        self.plant = plant_sim
        self.interlock = interlock
        self.state = state_mgr
        self.audit = audit_sink
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self._last_decision_type: Optional[DecisionType] = None
        self._decision_id_seq: int = 0

    async def start(self) -> None:
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self.running:
            start_time = time.time()
            try:
                self.step_tick()
            except Exception as e:
                print(f"[CONTROL LOOP ERROR] Exception during tick: {e}", file=sys.stderr)

            # Compute remaining time to maintain consistent 1.0s loop cadence
            elapsed = time.time() - start_time
            sleep_duration = max(0.05, 1.0 - elapsed)
            await asyncio.sleep(sleep_duration)

    def step_tick(self) -> DecisionRecord:
        now = time.time()
        iso_time = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Read sensors (Primary, Verification, Reported Flow)
        primary_ppm, verification_ppm, reported_flow = self.plant.read_sensors()

        # Actual physical flow for mixing physics
        # If flow sensor is not injected, actual_flow == reported_flow.
        # If flow sensor IS injected, physical flow remains baseline ~50.0 L/s.
        if self.plant.flow_injection is not None:
            actual_flow = self.plant.baseline_flow
        else:
            actual_flow = reported_flow

        # 2. Control algorithm: compute target pump dose
        # A proportional chemical feedforward controller toward 100.0 ppm setpoint:
        # requested_dose = primary_ppm * (nominal_flow / reported_flow)
        flow_ratio = self.plant.baseline_flow / max(reported_flow, 1.0)
        requested_dose = round(primary_ppm * flow_ratio, 2)

        # 3. Pass through Safety Instrumented System (SIS) interlock
        decision, actual_dose, reason = self.interlock.evaluate(
            requested_dose=requested_dose,
            primary_ppm=primary_ppm,
            verification_ppm=verification_ppm,
            flow_l_s=reported_flow,
            actual_flow_l_s=actual_flow
        )

        # 4. Advance physical plant model
        self.plant.step(actual_dose_ppm=actual_dose, actual_flow_l_s=actual_flow, dt=1.0)

        # 5. Build Decision Record
        self._decision_id_seq += 1
        record = DecisionRecord(
            id=self._decision_id_seq,
            run_id=self.state.run_id,
            ts=now,
            iso_time=iso_time,
            primary_ppm=primary_ppm,
            verification_ppm=verification_ppm,
            flow=reported_flow,
            requested_dose=requested_dose,
            actual_dose=actual_dose,
            resulting_ppm=self.plant.resulting_ppm,
            ph=self.plant.ph,
            interlock_on=self.interlock.enabled,
            decision=decision,
            reason=reason
        )

        # 6. Update in-memory state repository
        self.state.last_decision = record
        self.state.record_tick(
            ts=now,
            primary_ppm=primary_ppm,
            verification_ppm=verification_ppm,
            flow_l_s=reported_flow,
            requested_dose=requested_dose,
            actual_dose=actual_dose,
            resulting_ppm=self.plant.resulting_ppm,
            ph=self.plant.ph
        )

        # Handle events on state transitions or blocks
        if decision == DecisionType.BLOCKED:
            if self._last_decision_type != DecisionType.BLOCKED or self.interlock.consecutive_blocks % 5 == 1:
                self.state.add_event(
                    EventType.BLOCKED,
                    "DOSE COMMAND BLOCKED BY INTERLOCK",
                    reason
                )
                self.state.add_annotation("BLOCKED: " + reason.split(":")[0], "BLOCKED", "#ef4444")
        elif decision == DecisionType.ALLOWED and self._last_decision_type == DecisionType.BLOCKED:
            self.state.add_event(
                EventType.ALLOWED,
                "DOSE PERMITTED",
                "Operating conditions restored to nominal safe parameters."
            )

        self._last_decision_type = decision

        # 7. Asynchronously enqueue to SQLite audit sink
        self.audit.enqueue(record)

        # 8. Console logging for terminal observability
        stat_color = "\033[91m" if decision == DecisionType.BLOCKED else "\033[92m"
        reset_color = "\033[0m"
        print(
            f"[{iso_time}] [{self.state.run_id}] {stat_color}{decision.value:<7}{reset_color} | "
            f"Req: {requested_dose:>8.1f} ppm | Act: {actual_dose:>6.1f} ppm | "
            f"pH: {self.plant.ph:>5.2f} | P: {primary_ppm:>7.1f} | V: {verification_ppm:>7.1f} | "
            f"Flow: {reported_flow:>4.1f} L/s | {reason}"
        )

        return record
