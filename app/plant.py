import math
import random
from typing import Optional, Tuple


def calculate_ph(concentration_ppm: float) -> float:
    """
    Calculate water pH based on sodium hydroxide (NaOH) concentration in ppm.
    Natural treated water contains buffering alkalinity (bicarbonate buffer ~2 mEq/L)
    which maintains pH ~7.2-7.6 around nominal 100 ppm.

    Once NaOH exceeds ~150-200 ppm, buffer capacity is depleted and pH enters the
    elevated band (>8.5). Above ~800-1000 ppm, it enters the dangerous/corrosive
    band (>10.0), reaching pH ~12.5-13.3 at Oldsmar spike levels (11,100 ppm).
    """
    if concentration_ppm <= 0:
        return 7.0
    if concentration_ppm <= 100.0:
        # Buffer range: 7.2 to 7.6
        return round(7.2 + 0.4 * (concentration_ppm / 100.0), 2)

    # Logarithmic caustic dissociation once buffer is consumed
    ph = 7.6 + 2.8 * math.log10(concentration_ppm / 100.0)
    return round(min(max(ph, 6.0), 13.5), 2)


def get_ph_band(ph: float) -> str:
    if ph <= 8.5:
        return "safe"
    elif ph <= 10.0:
        return "elevated"
    else:
        return "dangerous"


class PlantSimulator:
    def __init__(self, seed: int = 42, tau_seconds: float = 4.5):
        self.seed = seed
        self.tau = tau_seconds
        self.rng = random.Random(seed)

        # Baseline physical parameters
        self.baseline_concentration: float = 100.0  # ppm NaOH
        self.baseline_flow: float = 50.0            # L/s

        # Live physical state
        self.tank_concentration: float = self.baseline_concentration
        self.feed_rate_mg_s: float = self.baseline_concentration * self.baseline_flow
        self.resulting_ppm: float = self.baseline_concentration
        self.ph: float = calculate_ph(self.tank_concentration)

        # Attack injection overrides (None = normal physical simulation)
        self.primary_injection: Optional[float] = None
        self.verification_injection: Optional[float] = None
        self.flow_injection: Optional[float] = None

    def read_sensors(self) -> Tuple[float, float, float]:
        """
        Returns (primary_ppm, verification_ppm, flow_l_s).
        Both sensor channels independently measure NaOH concentration.
        Flow is an environmental input with mild noise.
        """
        # Physical flow
        raw_flow = self.baseline_flow + self.rng.gauss(0.0, 0.35)
        raw_flow = max(45.0, min(55.0, raw_flow))

        # Sensor readings
        if self.primary_injection is not None:
            primary = self.primary_injection
        else:
            primary = self.baseline_concentration + self.rng.gauss(0.0, 0.8)

        if self.verification_injection is not None:
            verification = self.verification_injection
        else:
            verification = self.baseline_concentration + self.rng.gauss(0.0, 0.8)

        if self.flow_injection is not None:
            reported_flow = self.flow_injection
        else:
            reported_flow = raw_flow

        return round(primary, 2), round(verification, 2), round(reported_flow, 2)

    def step(self, actual_dose_ppm: float, actual_flow_l_s: float, dt: float = 1.0) -> None:
        """
        Advance plant model by dt seconds.
        - feed_rate_mg_s = actual_dose * flow_rate
        - resulting_ppm = feed_rate_mg_s / flow_rate
        - tank_concentration follows resulting_ppm with first-order lag
        - pH is derived from tank_concentration
        """
        # Mass injection rate in mg/s
        self.feed_rate_mg_s = round(actual_dose_ppm * actual_flow_l_s, 2)

        # Resulting concentration in the mixing header
        self.resulting_ppm = round(self.feed_rate_mg_s / actual_flow_l_s, 2)

        # First-order lag in the contact/storage tank
        # dC/dt = (C_resulting - C_tank) / tau
        alpha = 1.0 - math.exp(-dt / self.tau)
        self.tank_concentration += (self.resulting_ppm - self.tank_concentration) * alpha
        self.tank_concentration = round(max(0.0, self.tank_concentration), 2)

        # Update finished water pH
        self.ph = calculate_ph(self.tank_concentration)

    def inject_primary(self, value: Optional[float]) -> None:
        self.primary_injection = value

    def inject_verification(self, value: Optional[float]) -> None:
        self.verification_injection = value

    def inject_flow(self, value: Optional[float]) -> None:
        self.flow_injection = value

    def reset(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.primary_injection = None
        self.verification_injection = None
        self.flow_injection = None
        self.tank_concentration = self.baseline_concentration
        self.feed_rate_mg_s = self.baseline_concentration * self.baseline_flow
        self.resulting_ppm = self.baseline_concentration
        self.ph = calculate_ph(self.tank_concentration)
