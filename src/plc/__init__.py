"""AquaPhy Synthetic PLC Package."""

from src.plc.synthetic_plc import (
    SyntheticPLC,
    ModbusRegisters,
    PUMP_SCALE,
    FLOW_SCALE,
    CONC_SCALE,
    MASS_SCALE,
)

__all__ = [
    "SyntheticPLC",
    "ModbusRegisters",
    "PUMP_SCALE",
    "FLOW_SCALE",
    "CONC_SCALE",
    "MASS_SCALE",
]
