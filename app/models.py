from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class AttackVariant(str, Enum):
    OLDSMAR_SPIKE = "oldsmar_spike"
    SINGLE_CHANNEL_STEALTH = "single_channel_stealth"
    SLOW_RAMP = "slow_ramp"
    FLOW_FALSIFICATION = "flow_falsification"


class DecisionType(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


class EventType(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    INFO = "INFO"
    ATTACK = "ATTACK"


class InjectValueRequest(BaseModel):
    value: float = Field(..., description="Injected sensor value")


class InterlockToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Safety interlock switch state (True=ON, False=OFF)")


class EventItem(BaseModel):
    id: int
    ts: float
    time_str: str
    type: EventType
    message: str
    detail: str


class DecisionRecord(BaseModel):
    id: Optional[int] = None
    run_id: str
    ts: float
    iso_time: str
    primary_ppm: float
    verification_ppm: float
    flow: float
    requested_dose: float
    actual_dose: float
    resulting_ppm: float
    ph: float
    interlock_on: bool
    decision: DecisionType
    reason: str


class SensorState(BaseModel):
    primary_ppm: float
    verification_ppm: float
    flow_l_s: float
    primary_injected: bool
    verification_injected: bool
    flow_injected: bool


class ControlState(BaseModel):
    requested_dose_ppm: float
    actual_dose_ppm: float
    feed_rate_mg_s: float
    resulting_ppm: float
    tank_concentration_ppm: float
    ph: float
    ph_band: str  # "safe", "elevated", "dangerous"


class HistoryData(BaseModel):
    timestamps: List[float]
    time_labels: List[str]
    primary: List[float]
    verification: List[float]
    flow: List[float]
    requested_dose: List[float]
    actual_dose: List[float]
    resulting_ppm: List[float]
    ph: List[float]


class SystemStateResponse(BaseModel):
    run_id: str
    uptime_seconds: float
    interlock_on: bool
    system_status: str  # "NOMINAL", "BLOCKED", "DANGER"
    status_reason: str
    sensors: SensorState
    control: ControlState
    last_decision: Optional[DecisionRecord] = None
    history: HistoryData
    events: List[EventItem]
    active_attack: Optional[str] = None
    consecutive_blocks: int
    failsafe_active: bool
    annotations: List[Dict[str, Any]] = []


class RunSummary(BaseModel):
    run_id: str
    start_time: str
    total_decisions: int
    blocked_decisions: int
