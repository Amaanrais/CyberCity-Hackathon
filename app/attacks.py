import asyncio
import sys
from typing import Optional

from app.models import AttackVariant, EventType
from app.plant import PlantSimulator
from app.state import SystemStateManager


class AttackEngine:
    """
    Executes and coordinates the 4 attack variants.
    """

    def __init__(self, plant_sim: PlantSimulator, state_mgr: SystemStateManager):
        self.plant = plant_sim
        self.state = state_mgr
        self.ramp_task: Optional[asyncio.Task] = None

    async def trigger_attack(self, variant: str) -> dict:
        self.stop_active_attacks()

        if variant == AttackVariant.OLDSMAR_SPIKE.value or variant == "oldsmar_spike":
            # Primary jumps ~100 -> ~11,100 ppm. Verification untouched.
            self.plant.inject_primary(11100.0)
            self.state.active_attack = AttackVariant.OLDSMAR_SPIKE.value
            self.state.add_event(
                EventType.ATTACK,
                "ATTACK TRIGGERED: Oldsmar Spike",
                "Primary sensor falsified to 11,100 ppm. Verification untouched."
            )
            self.state.add_annotation("ATTACK: Oldsmar Spike (11,100 ppm)", "ATTACK", "#ef4444")
            return {"status": "success", "variant": variant, "message": "Primary sensor falsified to 11,100 ppm"}

        elif variant == AttackVariant.SINGLE_CHANNEL_STEALTH.value or variant == "single_channel_stealth":
            # Primary raised moderately (135 ppm). Within rate-of-change & hard-bound.
            self.plant.inject_primary(135.0)
            self.state.active_attack = AttackVariant.SINGLE_CHANNEL_STEALTH.value
            self.state.add_event(
                EventType.ATTACK,
                "ATTACK TRIGGERED: Single-Channel Stealth",
                "Primary sensor set to 135.0 ppm. Rate-of-change and hard-bound pass; tests cross-check."
            )
            self.state.add_annotation("ATTACK: Stealth (135 ppm)", "ATTACK", "#f59e0b")
            return {"status": "success", "variant": variant, "message": "Primary sensor falsified to 135 ppm"}

        elif variant == AttackVariant.SLOW_RAMP.value or variant == "slow_ramp":
            # Dual compromise: creeps primary up ~35 ppm/tick, dragging verification along.
            self.state.active_attack = AttackVariant.SLOW_RAMP.value
            self.state.add_event(
                EventType.ATTACK,
                "ATTACK TRIGGERED: Slow Ramp (Dual-Compromise)",
                "Both Primary and Verification ramping +35 ppm/s. Defeats cross-check & rate-of-change."
            )
            self.state.add_annotation("ATTACK: Dual Ramp (+35 ppm/s)", "ATTACK", "#8b5cf6")
            self.ramp_task = asyncio.create_task(self._slow_ramp_loop())
            return {"status": "success", "variant": variant, "message": "Dual sensor slow ramp initiated"}

        elif variant == AttackVariant.FLOW_FALSIFICATION.value or variant == "flow_falsification":
            # Flow reported low (15 L/s). Sensors untouched.
            self.plant.inject_flow(15.0)
            self.state.active_attack = AttackVariant.FLOW_FALSIFICATION.value
            self.state.add_event(
                EventType.ATTACK,
                "ATTACK TRIGGERED: Flow Falsification",
                "Reported flow falsified to 15.0 L/s. Controller drives pump to compensate mass."
            )
            self.state.add_annotation("ATTACK: Falsified Flow (15 L/s)", "ATTACK", "#06b6d4")
            return {"status": "success", "variant": variant, "message": "Flow reported low (15 L/s)"}

        else:
            return {"status": "error", "message": f"Unknown attack variant '{variant}'"}

    async def _slow_ramp_loop(self) -> None:
        current_val = 100.0
        step_increment = 35.0  # < 40 ppm/s max rate of change
        try:
            while True:
                current_val += step_increment
                self.plant.inject_primary(round(current_val, 1))
                self.plant.inject_verification(round(current_val, 1))
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[ATTACK ENGINE ERROR] Error in slow ramp loop: {e}", file=sys.stderr)

    def stop_active_attacks(self) -> None:
        if self.ramp_task and not self.ramp_task.done():
            self.ramp_task.cancel()
            self.ramp_task = None

        self.plant.inject_primary(None)
        self.plant.inject_verification(None)
        self.plant.inject_flow(None)
        self.state.active_attack = None
