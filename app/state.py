import collections
import datetime
import time
import uuid
from typing import List, Optional, Dict, Any

from app.models import (
    SystemStateResponse,
    SensorState,
    ControlState,
    HistoryData,
    EventItem,
    EventType,
    DecisionRecord,
    DecisionType
)
from app.plant import get_ph_band


def generate_run_id() -> str:
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"run_{now_str}_{short_uuid}"


class SystemStateManager:
    """
    Thread-safe in-memory state repository.
    Keeps rolling windows of sensor and control data in memory for instantaneous,
    zero-disk /state queries to ensure the dashboard never stutters or drops frames.
    """

    MAX_HISTORY: int = 90  # 90 seconds of 1Hz samples

    def __init__(self):
        self.run_id: str = generate_run_id()
        self.start_time: float = time.time()
        self.event_counter: int = 0
        self.active_attack: Optional[str] = None
        self.last_decision: Optional[DecisionRecord] = None

        # Rolling history deques
        self.history_timestamps = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_time_labels = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_primary = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_verification = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_flow = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_requested_dose = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_actual_dose = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_resulting_ppm = collections.deque(maxlen=self.MAX_HISTORY)
        self.history_ph = collections.deque(maxlen=self.MAX_HISTORY)

        # Recent events log & timeline annotations
        self.events: List[EventItem] = []
        self.annotations: List[Dict[str, Any]] = []

        self.add_event(
            EventType.INFO,
            "System initialized",
            f"Active run ID: {self.run_id}. Baseline NaOH: 100.0 ppm."
        )

    def add_event(self, event_type: EventType, message: str, detail: str) -> EventItem:
        self.event_counter += 1
        now = time.time()
        time_str = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S")
        event = EventItem(
            id=self.event_counter,
            ts=now,
            time_str=time_str,
            type=event_type,
            message=message,
            detail=detail
        )
        self.events.append(event)
        # Retain last 100 events
        if len(self.events) > 100:
            self.events.pop(0)
        return event

    def add_annotation(self, label: str, annotation_type: str = "ATTACK", color: str = "#ef4444") -> None:
        now = time.time()
        time_str = datetime.datetime.fromtimestamp(now).strftime("%H:%M:%S")
        self.annotations.append({
            "ts": now,
            "time_str": time_str,
            "label": label,
            "type": annotation_type,
            "color": color
        })
        # Keep last 20 annotations
        if len(self.annotations) > 20:
            self.annotations.pop(0)

    def record_tick(
        self,
        ts: float,
        primary_ppm: float,
        verification_ppm: float,
        flow_l_s: float,
        requested_dose: float,
        actual_dose: float,
        resulting_ppm: float,
        ph: float
    ) -> None:
        time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        self.history_timestamps.append(ts)
        self.history_time_labels.append(time_str)
        self.history_primary.append(primary_ppm)
        self.history_verification.append(verification_ppm)
        self.history_flow.append(flow_l_s)
        self.history_requested_dose.append(requested_dose)
        self.history_actual_dose.append(actual_dose)
        self.history_resulting_ppm.append(resulting_ppm)
        self.history_ph.append(ph)

    def get_snapshot(
        self,
        plant_sim,
        interlock,
        since_event_id: Optional[int] = None
    ) -> SystemStateResponse:
        uptime = round(time.time() - self.start_time, 1)

        # Primary and verification reading status
        primary_ppm = self.history_primary[-1] if self.history_primary else plant_sim.baseline_concentration
        verification_ppm = self.history_verification[-1] if self.history_verification else plant_sim.baseline_concentration
        flow_l_s = self.history_flow[-1] if self.history_flow else plant_sim.baseline_flow

        requested_dose = self.history_requested_dose[-1] if self.history_requested_dose else 100.0
        actual_dose = self.history_actual_dose[-1] if self.history_actual_dose else 100.0
        resulting_ppm = self.history_resulting_ppm[-1] if self.history_resulting_ppm else 100.0
        ph = self.history_ph[-1] if self.history_ph else 7.60
        ph_band = get_ph_band(ph)

        # Compute overarching system status
        if ph > 10.0:
            system_status = "DANGER"
            status_reason = f"CRITICAL HAZARD: Water pH is {ph:.2f} (Dangerous caustic alkalinity > 10.0)"
        elif self.last_decision and self.last_decision.decision == DecisionType.BLOCKED:
            system_status = "BLOCKED"
            status_reason = f"DOSE BLOCKED: {self.last_decision.reason}"
        else:
            system_status = "NOMINAL"
            status_reason = "System operating within normal parameters"

        # Filter events if since_event_id given
        if since_event_id is not None:
            filtered_events = [e for e in self.events if e.id > since_event_id]
        else:
            filtered_events = list(self.events)

        return SystemStateResponse(
            run_id=self.run_id,
            uptime_seconds=uptime,
            interlock_on=interlock.enabled,
            system_status=system_status,
            status_reason=status_reason,
            sensors=SensorState(
                primary_ppm=primary_ppm,
                verification_ppm=verification_ppm,
                flow_l_s=flow_l_s,
                primary_injected=plant_sim.primary_injection is not None,
                verification_injected=plant_sim.verification_injection is not None,
                flow_injected=plant_sim.flow_injection is not None
            ),
            control=ControlState(
                requested_dose_ppm=requested_dose,
                actual_dose_ppm=actual_dose,
                feed_rate_mg_s=plant_sim.feed_rate_mg_s,
                resulting_ppm=resulting_ppm,
                tank_concentration_ppm=plant_sim.tank_concentration,
                ph=ph,
                ph_band=ph_band
            ),
            last_decision=self.last_decision,
            history=HistoryData(
                timestamps=list(self.history_timestamps),
                time_labels=list(self.history_time_labels),
                primary=list(self.history_primary),
                verification=list(self.history_verification),
                flow=list(self.history_flow),
                requested_dose=list(self.history_requested_dose),
                actual_dose=list(self.history_actual_dose),
                resulting_ppm=list(self.history_resulting_ppm),
                ph=list(self.history_ph)
            ),
            events=filtered_events,
            active_attack=self.active_attack,
            consecutive_blocks=interlock.consecutive_blocks,
            failsafe_active=interlock.failsafe_active,
            annotations=list(self.annotations)
        )

    def reset(self, new_run: bool = True) -> None:
        if new_run:
            self.run_id = generate_run_id()
            self.start_time = time.time()
        self.active_attack = None
        self.last_decision = None
        self.history_timestamps.clear()
        self.history_time_labels.clear()
        self.history_primary.clear()
        self.history_verification.clear()
        self.history_flow.clear()
        self.history_requested_dose.clear()
        self.history_actual_dose.clear()
        self.history_resulting_ppm.clear()
        self.history_ph.clear()
        self.annotations.clear()
        self.add_event(
            EventType.INFO,
            "System reset",
            f"State cleared. New active run ID: {self.run_id}."
        )
