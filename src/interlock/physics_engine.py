"""AquaPhy Physics Engine: Dual-Horizon Invariant Validation.

Implements:
1. Instantaneous Safety Envelope:
   Calculates closed-form single-step ceiling u_max_inst(Q, C) via CSTR mass balance
   over a short-horizon predictive safety envelope such that predicted C(t + H) <= C_max.
2. Physics-Derived Nominal Baseline:
   Derives nominal mass dosing rate m_dot_nom(Q) and u_nom(Q) strictly from
   conservation of mass at target concentration C_target, independent of attacker history.
3. Cumulative Excess-Dose Tracker:
   Integrates excess mass max(0, m_dot_active - m_dot_nom(Q)) * dt over sliding window W (mg).
   Operates strictly on elapsed process/simulation time, independent of command packet arrival rate,
   and continues accumulating during idle gaps when an elevated command remains active.
4. Thread-Safe State Transitions:
   Internal lock protects mutable state (_history, _last_time, _process_time, _active_u,
   _last_u_req) across concurrent evaluate() and tick() invocations, preventing race
   conditions and mass double-counting under multithreaded command streams.
5. Defense Decision Engine:
   Yields deterministic decisions: NORMAL, CLAMPED_INSTANTANEOUS, CLAMPED_CUMULATIVE.

Distinction between timing parameters:
- dt: Discrete simulation integration timestep (nominal 0.1 s).
- H: Short-horizon predictive safety horizon (nominal 50.0 s, hydraulic residence time constant tau).
"""

from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Deque, Tuple
from src.simulation.cstr import CSTRParameters


class DefenseState(str, Enum):
    NORMAL = "NORMAL"
    CLAMPED_INSTANTANEOUS = "CLAMPED_INSTANTANEOUS"
    CLAMPED_CUMULATIVE = "CLAMPED_CUMULATIVE"
    FAILSAFE_HOLD = "FAILSAFE_HOLD"


@dataclass(frozen=True)
class InterlockParameters:
    """Configuration parameters for physical interlock enforcement.

    Attributes:
        cstr: CSTR physical constants.
        window_duration: Sliding window duration W (s) for cumulative tracking (default 60.0 s).
        mass_budget: Maximum cumulative excess chemical mass budget (mg) (default 500.0 mg architectural baseline).
        eval_dt: Simulation integration timestep dt (s) (default 0.1 s).
        horizon: Short-horizon predictive safety horizon H (s) (default 50.0 s, reactor time constant tau).
    """
    cstr: CSTRParameters = CSTRParameters()
    window_duration: float = 60.0  # Sliding window duration W (s)
    mass_budget: float = 500.0     # Architectural mass budget (mg); demo may configure accelerated profile
    eval_dt: float = 0.1          # Discrete simulation integration timestep dt (s)
    horizon: float = 50.0         # Predictive safety horizon H = tau = V / (Q_nom + k_decay*V) (s)


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of physical safety validation on a dosing command."""
    decision: DefenseState
    u_req: float         # Raw requested pump command [0.0, 1.0]
    u_safe: float        # Validated / clamped safe command [0.0, 1.0]
    u_max_inst: float    # Instantaneous safety ceiling [0.0, 1.0]
    u_nom: float         # Physics-derived nominal baseline [0.0, 1.0]
    m_dot_req: float     # Requested chemical mass rate (mg/s)
    m_dot_nom: float     # Nominal chemical mass rate (mg/s)
    m_excess: float      # Cumulative excess mass in current window (mg)
    m_budget: float      # Cumulative mass budget threshold (mg)
    flow: float          # Raw water flow Q (L/s)
    concentration: float # Effluent concentration C (mg/L)
    reason: str = ""     # Human-readable engineering rationale for audit logging


class PhysicsEngine:
    """Dual-horizon physical safety interlock calculation engine with thread-safe state synchronization."""

    def __init__(self, params: InterlockParameters | None = None) -> None:
        self.params = params or InterlockParameters()
        self.cstr = self.params.cstr
        # Re-entrant or standard mutex protecting all mutable engine state
        self._lock = threading.Lock()
        # History queue storing (timestamp, delta_excess_mass_mg)
        self._history: Deque[Tuple[float, float]] = deque()
        self._last_time: float | None = None
        self._process_time: float = 0.0
        self._last_safe_u: float = 0.40  # Default safe hold setpoint
        self._active_u: float = 0.40     # Currently active pump setpoint in process
        self._last_u_req: float = 0.40   # Last requested setpoint from SCADA / network

    @property
    def last_safe_u(self) -> float:
        with self._lock:
            return self._last_safe_u

    @property
    def active_u(self) -> float:
        with self._lock:
            return self._active_u

    @property
    def last_u_req(self) -> float:
        with self._lock:
            return self._last_u_req

    def reset(self) -> None:
        """Clear cumulative window history and reset state (thread-safe)."""
        with self._lock:
            self._history.clear()
            self._last_time = None
            self._process_time = 0.0
            self._last_safe_u = 0.40
            self._active_u = 0.40
            self._last_u_req = 0.40

    def compute_instantaneous_ceiling(self, Q: float, C: float, dt: float | None = None) -> float:
        """Calculate maximum permissible pump command u_max_inst for the predictive safety horizon H.

        Derived from the CSTR forward Euler inequality C(t + H) <= C_max:
            u_max = (1 / k_pump) * [ (V / H)*(C_max - C) - Q*(C_in - C) + k_decay*V*C ]
        Clamped to physical actuator limits [0.0, 1.0].

        Note: dt here represents the predictive safety horizon H (defaulting to
        reactor hydraulic retention time constant tau = 50.0 s), NOT the simulation
        integration timestep dt (0.1 s).
        """
        step_dt = float(dt if dt is not None else self.params.horizon)
        if step_dt <= 0:
            step_dt = self.params.horizon

        q_val = max(0.0, float(Q))
        c_val = max(0.0, float(C))
        v_val = max(1e-6, float(self.cstr.V))
        k_pump = max(1e-6, float(self.cstr.k_pump))

        # Dimensional breakdown:
        # term1: (V / H) * (C_max - C)   [mg/s]
        term1 = (v_val / step_dt) * (self.cstr.C_max - c_val)
        # term2: - Q * (C_in - C)        [mg/s]
        term2 = - q_val * (self.cstr.C_in - c_val)
        # term3: k_decay * V * C         [mg/s]
        term3 = self.cstr.k_decay * v_val * c_val

        u_raw = (term1 + term2 + term3) / k_pump
        return max(0.0, min(1.0, u_raw))

    def compute_nominal_baseline(self, Q: float) -> Tuple[float, float]:
        """Calculate nominal chemical mass rate m_dot_nom (mg/s) and command u_nom.

        Derived strictly from steady-state conservation of mass at C = C_target:
            m_dot_nom = Q * (C_target - C_in) + k_decay * V * C_target
            u_nom = m_dot_nom / k_pump
        Clamped to [0.0, 1.0]. Strictly independent of attacker-controlled command history.
        """
        q_val = max(0.0, float(Q))
        v_val = max(1e-6, float(self.cstr.V))
        k_pump = max(1e-6, float(self.cstr.k_pump))

        m_dot_nom = q_val * (self.cstr.C_target - self.cstr.C_in) + self.cstr.k_decay * v_val * self.cstr.C_target
        m_dot_nom = max(0.0, m_dot_nom)

        u_nom = max(0.0, min(1.0, m_dot_nom / k_pump))
        return m_dot_nom, u_nom

    def get_cumulative_excess(self, current_time: float | None = None) -> float:
        """Compute cumulative excess mass (mg) in the sliding window [now - W, now] (thread-safe)."""
        with self._lock:
            now = current_time if current_time is not None else self._process_time
            cutoff = now - self.params.window_duration

            # Prune expired samples outside sliding window
            while self._history and self._history[0][0] < cutoff:
                self._history.popleft()

            return sum(delta_m for _, delta_m in self._history)

    def _accumulate_locked(self, now: float, dt: float, u: float, Q: float) -> None:
        """Helper to accumulate excess mass injection over duration dt (caller must hold self._lock)."""
        if dt <= 0:
            return
        m_dot_nom, _ = self.compute_nominal_baseline(Q)
        m_dot_u = self.cstr.k_pump * max(0.0, min(1.0, u))
        delta_m_dot_excess = max(0.0, m_dot_u - m_dot_nom)
        delta_mass = delta_m_dot_excess * dt
        self._history.append((now, delta_mass))

    def tick(
        self,
        Q: float,
        C: float,
        current_time: float | None = None,
        dt: float | None = None,
    ) -> EvaluationResult:
        """Advance physical interlock state by elapsed process time during silence/idle periods (thread-safe).

        Allows excess chemical mass to continue accumulating while an elevated pump
        command remains active, ensuring the cumulative budget trips without requiring
        additional attacker write packets.
        """
        with self._lock:
            if dt is not None:
                effective_dt = max(0.0, float(dt))
            elif self._last_time is not None and current_time is not None:
                effective_dt = max(0.0, current_time - self._last_time)
            else:
                effective_dt = 0.0

            if current_time is not None:
                now = current_time
            else:
                self._process_time += effective_dt
                now = self._process_time

            q_val = max(0.0, float(Q))
            c_val = max(0.0, float(C))

            if effective_dt > 0:
                self._accumulate_locked(now, effective_dt, self._active_u, q_val)
                self._last_time = now
            elif self._last_time is None:
                self._last_time = now

            cutoff = now - self.params.window_duration
            while self._history and self._history[0][0] < cutoff:
                self._history.popleft()
            m_excess = sum(dm for _, dm in self._history)

            m_budget = self.params.mass_budget
            m_dot_nom, u_nom = self.compute_nominal_baseline(q_val)
            u_max_inst = self.compute_instantaneous_ceiling(q_val, c_val, dt=self.params.horizon)

            if m_excess > m_budget and (self._last_u_req > u_nom or self._active_u > u_nom):
                decision = DefenseState.CLAMPED_CUMULATIVE
                reason = (
                    f"Cumulative excess mass budget exhausted ({m_excess:.1f} mg > {m_budget:.1f} mg). "
                    f"Active setpoint clamped to nominal baseline."
                )
                u_safe = min(self._last_u_req, u_nom, u_max_inst)
                self._active_u = u_safe
            elif self._last_u_req > u_max_inst:
                decision = DefenseState.CLAMPED_INSTANTANEOUS
                reason = (
                    f"Requested setpoint exceeds instantaneous ceiling ({self._last_u_req:.3f} > {u_max_inst:.3f}). "
                    f"Clamped to short-horizon predictive ceiling."
                )
                u_safe = u_max_inst
                self._active_u = u_safe
            else:
                decision = DefenseState.NORMAL
                reason = "Operating within physical safety envelope."
                u_safe = self._last_u_req
                self._active_u = u_safe

            self._last_safe_u = u_safe
            m_dot_req = self.cstr.k_pump * self._last_u_req

            return EvaluationResult(
                decision=decision,
                u_req=self._last_u_req,
                u_safe=u_safe,
                u_max_inst=u_max_inst,
                u_nom=u_nom,
                m_dot_req=m_dot_req,
                m_dot_nom=m_dot_nom,
                m_excess=m_excess,
                m_budget=m_budget,
                flow=q_val,
                concentration=c_val,
                reason=reason,
            )

    def evaluate(
        self,
        u_req: float,
        Q: float,
        C: float,
        current_time: float | None = None,
        dt: float | None = None,
        horizon: float | None = None,
    ) -> EvaluationResult:
        """Validate an incoming dosing setpoint against both physical safety horizons (thread-safe).

        Args:
            u_req: Requested pump command from supervisory/attacker network packet [0.0, 1.0].
            Q: Current raw water flow telemetry (L/s).
            C: Current chemical concentration telemetry (mg/L).
            current_time: Optional explicit process timestamp for sliding window (s).
            dt: Explicit process-time-scaled elapsed duration (s) since last command/tick.

        Returns:
            EvaluationResult detailing the decision, safe command, and metrics.
        """
        with self._lock:
            q_val = max(0.0, float(Q))
            c_val = max(0.0, float(C))
            u_req_bounded = max(0.0, min(1.0, float(u_req)))

            # 1. Determine process-time elapsed dt
            if dt is not None:
                effective_dt = max(0.0, float(dt))
            elif self._last_time is not None and current_time is not None:
                effective_dt = max(0.0, current_time - self._last_time)
            else:
                effective_dt = 0.0

            if current_time is not None:
                now = current_time
            else:
                self._process_time += effective_dt
                now = self._process_time

            # 2. Accumulate elapsed process time at previous active command
            if effective_dt > 0:
                u_for_acc = u_req_bounded if self._last_time is None else self._active_u
                self._accumulate_locked(now, effective_dt, u_for_acc, q_val)
                self._last_time = now
            elif self._last_time is None:
                self._last_time = now

            # Prune window & calculate current cumulative excess mass
            cutoff = now - self.params.window_duration
            while self._history and self._history[0][0] < cutoff:
                self._history.popleft()
            m_excess = sum(dm for _, dm in self._history)
            m_budget = self.params.mass_budget

            # 3. Horizon 1: Short-horizon predictive safety envelope
            if horizon is not None:
                ceiling_dt = horizon
            elif dt is not None and dt >= 1.0:
                ceiling_dt = dt
            else:
                ceiling_dt = self.params.horizon
            u_max_inst = self.compute_instantaneous_ceiling(q_val, c_val, dt=ceiling_dt)

            # 4. Horizon 2: Physics-derived nominal baseline
            m_dot_nom, u_nom = self.compute_nominal_baseline(q_val)
            m_dot_req = self.cstr.k_pump * u_req_bounded

            self._last_u_req = u_req_bounded

            # 5. Defense Decision Logic
            if m_excess > m_budget and u_req_bounded > u_nom:
                decision = DefenseState.CLAMPED_CUMULATIVE
                reason = (
                    f"Cumulative excess mass budget exhausted ({m_excess:.1f} mg > {m_budget:.1f} mg). "
                    f"Requested setpoint clamped to nominal baseline."
                )
                u_safe = min(u_req_bounded, u_nom, u_max_inst)
            elif u_req_bounded > u_max_inst:
                decision = DefenseState.CLAMPED_INSTANTANEOUS
                reason = (
                    f"Requested setpoint exceeds instantaneous ceiling ({u_req_bounded:.3f} > {u_max_inst:.3f}). "
                    f"Clamped to short-horizon predictive ceiling."
                )
                u_safe = u_max_inst
            else:
                decision = DefenseState.NORMAL
                reason = "Requested setpoint validated within physical safety envelope."
                u_safe = u_req_bounded

            self._active_u = u_safe
            self._last_safe_u = u_safe

            return EvaluationResult(
                decision=decision,
                u_req=u_req_bounded,
                u_safe=u_safe,
                u_max_inst=u_max_inst,
                u_nom=u_nom,
                m_dot_req=m_dot_req,
                m_dot_nom=m_dot_nom,
                m_excess=m_excess,
                m_budget=m_budget,
                flow=q_val,
                concentration=c_val,
                reason=reason,
            )
