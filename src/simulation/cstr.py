"""Continuous Stirred Tank Reactor (CSTR) Process Simulation for AquaPhy.

Models the disinfection contact chamber dynamics via hydraulic mass balance:
    dC/dt = (Q/V)*(C_in - C) + (k_pump * u)/V - k_decay * C

All units are in standard SI/engineering units:
    C: mg/L (chemical concentration)
    Q: L/s (volumetric flow rate)
    V: L (liquid volume)
    k_pump: mg/s (maximum chemical mass delivery rate at u=1.0)
    u: [0.0, 1.0] (normalized pump setpoint)
    k_decay: 1/s (first-order decay constant)
    dt: s (integration timestep)
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class CSTRParameters:
    """Synthetic physical parameters for the CSTR contact tank."""
    V: float = 1000.0           # Tank liquid volume (L)
    Q_nominal: float = 10.0      # Nominal raw water inflow (L/s)
    C_in: float = 0.0           # Inflow raw water chemical concentration (mg/L)
    C_target: float = 2.0       # Target residual disinfectant concentration (mg/L)
    C_max: float = 4.0          # Maximum allowable safety limit (EPA MRDL) (mg/L)
    k_pump: float = 100.0       # Maximum chemical feed delivery rate (mg/s)
    k_decay: float = 0.01       # Disinfectant first-order decay rate (1/s)
    dt: float = 0.1             # Simulation integration timestep (s)


class CSTRSimulation:
    """Forward-Euler simulator for CSTR chemical disinfection contact chamber."""

    def __init__(
        self,
        params: CSTRParameters | None = None,
        initial_C: float | None = None,
        initial_Q: float | None = None,
    ) -> None:
        self.params = params or CSTRParameters()
        self._C: float = initial_C if initial_C is not None else self.params.C_target
        self._Q: float = initial_Q if initial_Q is not None else self.params.Q_nominal
        self._V: float = self.params.V
        self._time: float = 0.0
        self._last_u: float = 0.40  # nominal at (Q=10, C=2.0)

    @property
    def concentration(self) -> float:
        """Current disinfectant concentration in tank effluent (mg/L)."""
        return self._C

    @property
    def flow(self) -> float:
        """Current raw water volumetric flow rate (L/s)."""
        return self._Q

    @property
    def volume(self) -> float:
        """Current tank liquid volume (L)."""
        return self._V

    @property
    def time(self) -> float:
        """Elapsed simulation time (s)."""
        return self._time

    @property
    def last_u(self) -> float:
        """Last applied pump setpoint [0.0, 1.0]."""
        return self._last_u

    def reset(self, initial_C: float | None = None, initial_Q: float | None = None) -> None:
        """Reset simulation state."""
        self._C = initial_C if initial_C is not None else self.params.C_target
        self._Q = initial_Q if initial_Q is not None else self.params.Q_nominal
        self._time = 0.0
        self._last_u = 0.40

    def compute_dC_dt(self, u: float, Q: float | None = None, C: float | None = None, V: float | None = None) -> float:
        """Calculate concentration rate of change dC/dt (mg/(L*s)).

        Applies physical bounds:
            - u is clamped to [0.0, 1.0]
            - Q is non-negative
            - V is guarded against zero-division (epsilon = 1e-6)
        """
        u_bounded = max(0.0, min(1.0, float(u)))
        q_val = max(0.0, float(Q if Q is not None else self._Q))
        c_val = max(0.0, float(C if C is not None else self._C))
        v_val = max(1e-6, float(V if V is not None else self._V))

        # (Q/V) * (C_in - C)
        convective_term = (q_val / v_val) * (self.params.C_in - c_val)
        # (k_pump * u) / V
        dosing_term = (self.params.k_pump * u_bounded) / v_val
        # - k_decay * C
        decay_term = -self.params.k_decay * c_val

        return convective_term + dosing_term + decay_term

    def step(self, u: float, Q: float | None = None, dt: float | None = None) -> float:
        """Advance the simulation by one discrete timestep using forward Euler.

        Args:
            u: Chemical dosing pump command setpoint [0.0, 1.0].
            Q: Raw water volumetric inflow rate (L/s). If None, keeps current flow.
            dt: Timestep duration (s). If None, uses params.dt.

        Returns:
            Updated chemical concentration C (mg/L).
        """
        step_dt = float(dt if dt is not None else self.params.dt)
        if step_dt <= 0:
            return self._C

        if Q is not None:
            self._Q = max(0.0, float(Q))

        self._last_u = max(0.0, min(1.0, float(u)))

        dC_dt = self.compute_dC_dt(u=self._last_u, Q=self._Q, C=self._C, V=self._V)

        # Forward Euler update with non-negative concentration floor
        c_next = self._C + step_dt * dC_dt
        self._C = max(0.0, c_next)
        self._time += step_dt

        return self._C

    def steady_state_concentration(self, u: float, Q: float | None = None) -> float:
        """Analytical steady-state concentration for given u and Q.

        At steady state dC/dt = 0:
            C_ss = (Q * C_in + k_pump * u) / (Q + k_decay * V)
        """
        u_bounded = max(0.0, min(1.0, float(u)))
        q_val = max(0.0, float(Q if Q is not None else self._Q))
        denominator = q_val + self.params.k_decay * self._V
        if denominator <= 1e-9:
            return 0.0
        numerator = q_val * self.params.C_in + self.params.k_pump * u_bounded
        return max(0.0, numerator / denominator)
