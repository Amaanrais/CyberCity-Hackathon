"""AquaPhy Local Audit Trail Logger.

Implements an append-only JSONL audit log for interlock safety evaluations,
clamping events, and state transitions without external databases.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, Optional


class AuditLogger:
    """Minimal thread-safe append-only JSONL audit logger."""

    def __init__(self, log_path: Optional[str | Path] = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._lock = threading.Lock()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(
        self,
        requested_pump_command: float,
        safe_pump_command: float,
        flow: float,
        concentration: float,
        instantaneous_ceiling: float,
        nominal_command: float,
        cumulative_excess_mass: float,
        defense_state: str,
        decision_reason: str,
        timestamp: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an interlock clamp or decision record."""
        record: Dict[str, Any] = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "requested_pump_command": float(round(requested_pump_command, 4)),
            "safe_pump_command": float(round(safe_pump_command, 4)),
            "Q": float(round(flow, 3)),
            "C": float(round(concentration, 4)),
            "instantaneous_ceiling": float(round(instantaneous_ceiling, 4)),
            "nominal_command": float(round(nominal_command, 4)),
            "cumulative_excess_mass": float(round(cumulative_excess_mass, 2)),
            "defense_state": str(defense_state),
            "decision_reason": str(decision_reason),
        }
        if extra:
            record["extra"] = extra

        if self.log_path:
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")

        return record
