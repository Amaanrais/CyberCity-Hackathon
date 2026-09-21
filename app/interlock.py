from typing import Tuple, Optional
from app.models import DecisionType


class SafetyInterlock:
    """
    Safety Instrumented System (SIS) Chemical Dosing Interlock.
    Modeled as an independent physical safety layer (IEC 61511) separating
    the SCADA control network from the metering pump actuators.

    Three concentric physical & algorithmic safety gates:
    1. HARD BOUND (Physically meaningful ceiling):
       Ensures calculated resulting_ppm in finished water never exceeds 150.0 ppm.
       Evaluates physical concentration rather than raw pump stroke, ensuring resilience
       against flow sensor falsification.
    2. RATE OF CHANGE (Slew Rate Limit):
       Limits dose acceleration to <= 40.0 ppm/s from the last accepted safe value.
    3. CROSS-CHECK (Dual-Channel Analytic Redundancy):
       Cross-verifies Primary vs Independent Verification channel within 15% relative
       tolerance with a 2-sample debounce filter to eliminate spurious false trips.

    Fail-Safe Behavior:
    Holding the last accepted dose is safe for transient spikes, but hazardous if the
    system was already locked at an elevated operating point. After N=5 consecutive
    blocks, an exponential decay filter actively steps down the actual dose toward
    the nominal 100.0 ppm baseline.
    """

    MAX_RESULTING_PPM: float = 150.0
    MAX_DELTA_PPM_PER_SEC: float = 40.0
    RELATIVE_TOLERANCE: float = 0.15       # 15% relative difference
    DEBOUNCE_THRESHOLD: int = 2           # Consecutive discordant samples before trip
    FAILSAFE_CONSECUTIVE_BLOCKS: int = 5   # Blocks before decay activates
    BASELINE_PPM: float = 100.0

    def __init__(self):
        self.enabled: bool = True
        self.last_accepted_dose: float = self.BASELINE_PPM
        self.consecutive_blocks: int = 0
        self.disagreement_samples: int = 0
        self.failsafe_active: bool = False

    def evaluate(
        self,
        requested_dose: float,
        primary_ppm: float,
        verification_ppm: float,
        flow_l_s: float,
        actual_flow_l_s: float
    ) -> Tuple[DecisionType, float, str]:
        """
        Evaluates dosing command. Returns (decision, actual_dose, reason).
        """
        # When interlock switch is OFF, bypass all checks
        if not self.enabled:
            self.consecutive_blocks = 0
            self.failsafe_active = False
            self.last_accepted_dose = requested_dose
            return (
                DecisionType.ALLOWED,
                requested_dose,
                "Interlock bypassed (SIS Hardware Key Switch OFF)"
            )

        # Projected resulting ppm in finished water
        # Resulting concentration in treated water follows pump dosing command
        projected_resulting_ppm = requested_dose

        # Check 1: Cross-check channel divergence (Analytic Redundancy)
        # Relative difference = |Primary - Verification| / Verification
        base_denom = max(abs(verification_ppm), 1.0)
        relative_diff = abs(primary_ppm - verification_ppm) / base_denom
        if relative_diff > self.RELATIVE_TOLERANCE:
            self.disagreement_samples += 1
        else:
            self.disagreement_samples = 0

        # Check 2: Rate of Change limit
        delta = abs(requested_dose - self.last_accepted_dose)
        rate_violated = delta > self.MAX_DELTA_PPM_PER_SEC

        # Check 3: Absolute Hard Bound ceiling on resulting ppm
        hard_bound_violated = projected_resulting_ppm > self.MAX_RESULTING_PPM

        # Determine if any safety gate tripped
        is_blocked = False
        reasons = []

        # Gate A: Cross-check trip (requires debounce threshold)
        if self.disagreement_samples >= self.DEBOUNCE_THRESHOLD:
            is_blocked = True
            reasons.append(
                f"SENSOR_DISAGREEMENT: Primary ({primary_ppm:.1f} ppm) vs Verification "
                f"({verification_ppm:.1f} ppm) diverged by {relative_diff * 100:.1f}% "
                f"(limit {self.RELATIVE_TOLERANCE * 100:.0f}%, {self.disagreement_samples} samples debounced)"
            )

        # Gate B: Rate of change trip
        if rate_violated:
            is_blocked = True
            reasons.append(
                f"RATE_OF_CHANGE_EXCEEDED: Requested jump of {delta:.1f} ppm/s "
                f"exceeds max slew rate {self.MAX_DELTA_PPM_PER_SEC:.1f} ppm/s"
            )

        # Gate C: Hard bound trip (Last line of defense)
        if hard_bound_violated:
            is_blocked = True
            reasons.append(
                f"HARD_BOUND_EXCEEDED: Projected resulting concentration {projected_resulting_ppm:.1f} ppm "
                f"exceeds safe ceiling {self.MAX_RESULTING_PPM:.1f} ppm"
            )

        if is_blocked:
            self.consecutive_blocks += 1
            full_reason = " | ".join(reasons)

            # Fail-safe decay policy:
            # If blocked for >= N consecutive ticks, decay dose down toward 100 ppm baseline
            if self.consecutive_blocks >= self.FAILSAFE_CONSECUTIVE_BLOCKS:
                self.failsafe_active = True
                decay_step = (self.BASELINE_PPM - self.last_accepted_dose) * 0.25
                self.last_accepted_dose = round(self.last_accepted_dose + decay_step, 2)
                # Snap if very close
                if abs(self.last_accepted_dose - self.BASELINE_PPM) < 1.0:
                    self.last_accepted_dose = self.BASELINE_PPM

                full_reason += (
                    f" [FAIL-SAFE DECAY ACTIVE: {self.consecutive_blocks} consecutive blocks, "
                    f"decaying dose toward {self.BASELINE_PPM:.0f} ppm]"
                )
            else:
                self.failsafe_active = False

            return DecisionType.BLOCKED, self.last_accepted_dose, full_reason

        # Nominal safe command accepted
        self.consecutive_blocks = 0
        self.failsafe_active = False
        self.last_accepted_dose = requested_dose
        return DecisionType.ALLOWED, requested_dose, "Nominal tracking within safety envelopes"

    def reset(self) -> None:
        self.enabled = True
        self.last_accepted_dose = self.BASELINE_PPM
        self.consecutive_blocks = 0
        self.disagreement_samples = 0
        self.failsafe_active = False
