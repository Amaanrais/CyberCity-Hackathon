"""AquaPhy Bump-in-the-Wire Modbus TCP Proxy.

Intercepts Modbus TCP write commands (FC06, FC16) destined for the water-treatment PLC.
Validates chemical dosing setpoints against instantaneous and cumulative physics invariants.
Clamps out-of-bounds commands in-flight before forwarding to the PLC.
Protects process telemetry registers (Flow Q and Concentration C) so they are strictly read-only
from the attacker/SCADA command path.
Tracks cumulative excess mass using elapsed process time across idle gaps and silent periods.
Maintains an append-only JSONL local audit trail.
Implements prototype fail-safe behavior (holding last known-safe setpoint on communication loss).
"""

from __future__ import annotations
import logging
from pathlib import Path
import socket
import struct
import threading
import time
from typing import Optional, Set, Tuple
from src.interlock.physics_engine import (
    PhysicsEngine,
    DefenseState,
    EvaluationResult,
    InterlockParameters,
)
from src.interlock.audit import AuditLogger
from src.plc.synthetic_plc import (
    ModbusRegisters,
    PUMP_SCALE,
    FLOW_SCALE,
    CONC_SCALE,
)

logger = logging.getLogger("AquaPhyProxy")

# Registers that are simulation/PLC-owned and must NEVER be writable through the proxy
PROTECTED_TELEMETRY_REGISTERS: Set[int] = {
    ModbusRegisters.FLOW_RATE,
    ModbusRegisters.CONCENTRATION,
    ModbusRegisters.STATUS_CODE,
    ModbusRegisters.CUMULATIVE_EXCESS,
    ModbusRegisters.NOMINAL_BASELINE,
    ModbusRegisters.INSTANTANEOUS_CEILING,
}


class ModbusProxy:
    """Inline Modbus TCP Interlock Proxy."""

    def __init__(
        self,
        listen_host: str = "127.0.0.1",
        listen_port: int = 5020,
        plc_host: str = "127.0.0.1",
        plc_port: int = 5021,
        engine: Optional[PhysicsEngine] = None,
        telemetry_poll_interval: float = 0.05,
        time_scale: float = 1.0,
        audit_log_path: Optional[str | Path] = "data/audit_log.jsonl",
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.plc_host = plc_host
        self.plc_port = plc_port
        self.engine = engine or PhysicsEngine()
        self.telemetry_poll_interval = telemetry_poll_interval
        self.time_scale = max(0.01, float(time_scale))
        self.audit_logger = AuditLogger(audit_log_path) if audit_log_path else None

        self._running = False
        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._telemetry_thread: Optional[threading.Thread] = None
        self._client_threads: list[threading.Thread] = []

        self._lock = threading.Lock()
        self._cached_q: float = 10.0
        self._cached_c: float = 2.0
        self._latest_eval: Optional[EvaluationResult] = None
        self._state: DefenseState = DefenseState.NORMAL
        self._last_safe_u: float = 0.40
        self._downstream_healthy: bool = False
        self._trans_id_counter: int = 1000
        self._last_interlock_wall_time: float = time.monotonic()

    def _get_process_dt(self) -> float:
        """Atomically compute elapsed process-time dt since last interlock call and advance wall anchor."""
        with self._lock:
            now = time.monotonic()
            dt_wall = now - self._last_interlock_wall_time
            self._last_interlock_wall_time = now
            return max(0.0, dt_wall * self.time_scale)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_state(self) -> DefenseState:
        with self._lock:
            return self._state

    @property
    def latest_result(self) -> Optional[EvaluationResult]:
        with self._lock:
            return self._latest_eval

    @property
    def last_safe_u(self) -> float:
        with self._lock:
            return self._last_safe_u

    def _next_trans_id(self) -> int:
        with self._lock:
            self._trans_id_counter = (self._trans_id_counter + 1) % 65000
            return self._trans_id_counter

    def _send_plc_raw(self, trans_id: int, pdu: bytes, timeout: float = 1.0) -> Optional[bytes]:
        """Send a single Modbus transaction to downstream PLC and return response PDU."""
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.plc_host, self.plc_port))

            header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)
            sock.sendall(header + pdu)

            resp_header = b""
            while len(resp_header) < 7:
                chunk = sock.recv(7 - len(resp_header))
                if not chunk:
                    return None
                resp_header += chunk

            _, _, r_len, _ = struct.unpack(">HHHB", resp_header)
            pdu_len = r_len - 1
            resp_pdu = b""
            while len(resp_pdu) < pdu_len:
                chunk = sock.recv(pdu_len - len(resp_pdu))
                if not chunk:
                    return None
                resp_pdu += chunk

            return resp_pdu
        except Exception:
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def _poll_plc_telemetry(self) -> bool:
        """Poll current Flow (Q) and Concentration (C) from downstream PLC."""
        # Read holding registers 1..2 (Flow and Concentration)
        read_pdu = struct.pack(">BHH", 0x03, ModbusRegisters.FLOW_RATE, 2)
        resp = self._send_plc_raw(self._next_trans_id(), read_pdu, timeout=0.5)

        if resp and len(resp) >= 6 and resp[0] == 0x03:
            q_raw, c_raw = struct.unpack(">HH", resp[2:6])
            with self._lock:
                self._cached_q = q_raw / FLOW_SCALE
                self._cached_c = c_raw / CONC_SCALE
                self._downstream_healthy = True
            return True
        else:
            with self._lock:
                prev_healthy = self._downstream_healthy
                self._downstream_healthy = False
                self._state = DefenseState.FAILSAFE_HOLD
            if prev_healthy and self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=self._last_safe_u,
                    safe_pump_command=self._last_safe_u,
                    flow=self._cached_q,
                    concentration=self._cached_c,
                    instantaneous_ceiling=0.0,
                    nominal_command=0.40,
                    cumulative_excess_mass=self.engine.get_cumulative_excess(),
                    defense_state=DefenseState.FAILSAFE_HOLD.value,
                    decision_reason="Downstream PLC unreachable during telemetry polling; entered FAILSAFE_HOLD.",
                )
            return False

    def _tick_interlock(self, dt_process: float) -> None:
        """Advance physical interlock cumulative tracking by elapsed process time.

        If cumulative excess mass breaches budget during silence/idle gap,
        transitions to CLAMPED_CUMULATIVE and automatically clamps the PLC
        pump setpoint to safe nominal u_nom without requiring an attacker write.
        """
        with self._lock:
            q = self._cached_q
            c = self._cached_c
            healthy = self._downstream_healthy
            prev_state = self._state

        if not healthy:
            return

        eval_res = self.engine.tick(Q=q, C=c, dt=dt_process)

        with self._lock:
            self._latest_eval = eval_res
            self._state = eval_res.decision
            self._last_safe_u = eval_res.u_safe

        # If state transitioned to CLAMPED_CUMULATIVE during silence
        if eval_res.decision == DefenseState.CLAMPED_CUMULATIVE and prev_state != DefenseState.CLAMPED_CUMULATIVE:
            logger.warning(
                "Cumulative budget exhausted during idle gap (M_excess=%.1f mg > %.1f mg). Clamping PLC setpoint to u_nom=%.2f",
                eval_res.m_excess, eval_res.m_budget, eval_res.u_nom
            )
            # Enforce clamp on PLC immediately
            u_safe_reg = int(round(eval_res.u_safe * PUMP_SCALE))
            clamp_pdu = struct.pack(">BHH", 0x06, ModbusRegisters.PUMP_SETPOINT, u_safe_reg)
            self._send_plc_raw(self._next_trans_id(), clamp_pdu)

            # Update PLC diagnostic registers
            threading.Thread(target=self._update_plc_diagnostics, args=(eval_res,), daemon=True).start()

            # Record in audit trail
            if self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=eval_res.u_req,
                    safe_pump_command=eval_res.u_safe,
                    flow=eval_res.flow,
                    concentration=eval_res.concentration,
                    instantaneous_ceiling=eval_res.u_max_inst,
                    nominal_command=eval_res.u_nom,
                    cumulative_excess_mass=eval_res.m_excess,
                    defense_state=eval_res.decision.value,
                    decision_reason=eval_res.reason,
                )

    def _telemetry_loop(self) -> None:
        """Background loop updating local cached telemetry from PLC and ticking interlock."""
        while self._running:
            # Poll telemetry from PLC
            self._poll_plc_telemetry()

            # Advance interlock cumulative tracker by elapsed process time since last tick/command
            dt_process = self._get_process_dt()
            self._tick_interlock(dt_process)

            sleep_sec = max(0.005, self.telemetry_poll_interval / self.time_scale)
            time.sleep(sleep_sec)

    def _update_plc_diagnostics(self, eval_res: EvaluationResult) -> None:
        """Asynchronously notify PLC of current interlock status and ceiling metrics."""
        status_map = {
            DefenseState.NORMAL: 0,
            DefenseState.CLAMPED_INSTANTANEOUS: 1,
            DefenseState.CLAMPED_CUMULATIVE: 2,
            DefenseState.FAILSAFE_HOLD: 3,
        }
        code = status_map.get(eval_res.decision, 0)
        diag_pdu = struct.pack(
            ">BHHBHHHH",
            0x10,
            ModbusRegisters.STATUS_CODE,
            4,
            8,
            code,
            int(round(eval_res.m_excess * 10.0)),
            int(round(eval_res.u_nom * PUMP_SCALE)),
            int(round(eval_res.u_max_inst * PUMP_SCALE)),
        )
        self._send_plc_raw(self._next_trans_id(), diag_pdu, timeout=0.2)

    def process_and_forward(self, pdu: bytes) -> bytes:
        """Inspect, validate, clamp if necessary, and forward Modbus PDU to PLC.

        Guarantees:
        - Only ModbusRegisters.PUMP_SETPOINT may be written by attacker/SCADA.
        - Attempts to write protected telemetry (Flow Q, Concentration C, etc.) are blocked.
        - Safe commands are forwarded; unsafe commands are clamped in-flight.
        """
        if len(pdu) < 1:
            return b"\x80\x01"

        func_code = pdu[0]

        # Intercept Write Single Register (FC06)
        if func_code == 0x06 and len(pdu) >= 5:
            addr, val = struct.unpack(">HH", pdu[1:5])
            if addr == ModbusRegisters.PUMP_SETPOINT:
                return self._handle_pump_write(addr, val, pdu)
            else:
                # HIGH PRIORITY FIX 1: Reject writes to protected telemetry/diagnostic registers
                logger.warning("Blocked unauthorized FC06 write attempt to register %d through proxy", addr)
                return bytes([0x06 | 0x80, 0x02])  # Modbus Exception 0x02: Illegal Data Address

        # Intercept Write Multiple Registers (FC16)
        elif func_code == 0x10 and len(pdu) >= 7:
            start_addr, count = struct.unpack(">HH", pdu[1:5])
            target_range = range(start_addr, start_addr + count)
            # HIGH PRIORITY FIX 1: If any register in range is not PUMP_SETPOINT, reject
            if any(a != ModbusRegisters.PUMP_SETPOINT for a in target_range):
                logger.warning(
                    "Blocked unauthorized FC16 write attempt spanning registers %d..%d through proxy",
                    start_addr, start_addr + count - 1,
                )
                return bytes([0x10 | 0x80, 0x02])  # Modbus Exception 0x02: Illegal Data Address

            if start_addr == ModbusRegisters.PUMP_SETPOINT and count == 1:
                return self._handle_multi_pump_write(start_addr, count, pdu)
            return bytes([0x10 | 0x80, 0x02])

        # Block unauthorized coil writes
        elif func_code in (0x05, 0x0F):
            logger.warning("Blocked unauthorized coil write attempt (FC0x%02X) through proxy", func_code)
            return bytes([func_code | 0x80, 0x01])

        # For all read commands (FC03, etc.), transparently forward to PLC for SCADA monitoring
        resp = self._send_plc_raw(self._next_trans_id(), pdu)
        if resp is None:
            with self._lock:
                self._state = DefenseState.FAILSAFE_HOLD
            return bytes([func_code | 0x80, 0x04])  # Slave device failure
        return resp

    def _handle_pump_write(self, addr: int, val: int, orig_pdu: bytes) -> bytes:
        """Handle dosing pump write setpoint validation and clamping."""
        with self._lock:
            q = self._cached_q
            c = self._cached_c
            healthy = self._downstream_healthy

        # Failsafe check
        if not healthy:
            with self._lock:
                self._state = DefenseState.FAILSAFE_HOLD
            if self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=val / PUMP_SCALE,
                    safe_pump_command=self._last_safe_u,
                    flow=q,
                    concentration=c,
                    instantaneous_ceiling=0.0,
                    nominal_command=0.40,
                    cumulative_excess_mass=self.engine.get_cumulative_excess(),
                    defense_state=DefenseState.FAILSAFE_HOLD.value,
                    decision_reason="Downstream PLC unreachable during write; entered FAILSAFE_HOLD.",
                )
            return bytes([0x06 | 0x80, 0x04])

        dt_process = self._get_process_dt()
        u_req = val / PUMP_SCALE
        eval_res = self.engine.evaluate(u_req=u_req, Q=q, C=c, dt=dt_process)

        with self._lock:
            self._latest_eval = eval_res
            self._state = eval_res.decision
            self._last_safe_u = eval_res.u_safe

        # Prepare forwarded PDU: if clamped, rewrite register value to u_safe!
        u_safe_reg = int(round(eval_res.u_safe * PUMP_SCALE))
        forward_pdu = struct.pack(">BHH", 0x06, addr, u_safe_reg)

        resp = self._send_plc_raw(self._next_trans_id(), forward_pdu)
        if resp is None:
            with self._lock:
                self._state = DefenseState.FAILSAFE_HOLD
            if self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=u_req,
                    safe_pump_command=eval_res.u_safe,
                    flow=eval_res.flow,
                    concentration=eval_res.concentration,
                    instantaneous_ceiling=eval_res.u_max_inst,
                    nominal_command=eval_res.u_nom,
                    cumulative_excess_mass=eval_res.m_excess,
                    defense_state=DefenseState.FAILSAFE_HOLD.value,
                    decision_reason="Forwarding command to PLC failed; entered FAILSAFE_HOLD.",
                )
            return bytes([0x06 | 0x80, 0x04])

        # Async update PLC diagnostic registers
        threading.Thread(target=self._update_plc_diagnostics, args=(eval_res,), daemon=True).start()

        # HIGH PRIORITY FIX 6: Audit logging
        if self.audit_logger:
            self.audit_logger.log_decision(
                requested_pump_command=u_req,
                safe_pump_command=eval_res.u_safe,
                flow=eval_res.flow,
                concentration=eval_res.concentration,
                instantaneous_ceiling=eval_res.u_max_inst,
                nominal_command=eval_res.u_nom,
                cumulative_excess_mass=eval_res.m_excess,
                defense_state=eval_res.decision.value,
                decision_reason=eval_res.reason,
            )

        # Return standard Modbus response echoing the validated/clamped write
        return forward_pdu

    def _handle_multi_pump_write(self, start_addr: int, count: int, orig_pdu: bytes) -> bytes:
        """Handle multiple register write containing pump setpoint."""
        with self._lock:
            q = self._cached_q
            c = self._cached_c
            healthy = self._downstream_healthy

        if not healthy:
            with self._lock:
                self._state = DefenseState.FAILSAFE_HOLD
            if self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=self._last_safe_u,
                    safe_pump_command=self._last_safe_u,
                    flow=q,
                    concentration=c,
                    instantaneous_ceiling=0.0,
                    nominal_command=0.40,
                    cumulative_excess_mass=self.engine.get_cumulative_excess(),
                    defense_state=DefenseState.FAILSAFE_HOLD.value,
                    decision_reason="Downstream PLC unreachable during multi-write; entered FAILSAFE_HOLD.",
                )
            return bytes([0x10 | 0x80, 0x04])

        # Find offset of pump setpoint in the byte payload
        byte_count = orig_pdu[5]
        offset = 6 + (ModbusRegisters.PUMP_SETPOINT - start_addr) * 2
        val = struct.unpack(">H", orig_pdu[offset : offset + 2])[0]
        u_req = val / PUMP_SCALE

        dt_process = self._get_process_dt()
        eval_res = self.engine.evaluate(u_req=u_req, Q=q, C=c, dt=dt_process)
        with self._lock:
            self._latest_eval = eval_res
            self._state = eval_res.decision
            self._last_safe_u = eval_res.u_safe

        u_safe_reg = int(round(eval_res.u_safe * PUMP_SCALE))
        pdu_bytearray = bytearray(orig_pdu)
        pdu_bytearray[offset : offset + 2] = struct.pack(">H", u_safe_reg)
        forward_pdu = bytes(pdu_bytearray)

        resp = self._send_plc_raw(self._next_trans_id(), forward_pdu)
        if resp is None:
            with self._lock:
                self._state = DefenseState.FAILSAFE_HOLD
            if self.audit_logger:
                self.audit_logger.log_decision(
                    requested_pump_command=u_req,
                    safe_pump_command=eval_res.u_safe,
                    flow=eval_res.flow,
                    concentration=eval_res.concentration,
                    instantaneous_ceiling=eval_res.u_max_inst,
                    nominal_command=eval_res.u_nom,
                    cumulative_excess_mass=eval_res.m_excess,
                    defense_state=DefenseState.FAILSAFE_HOLD.value,
                    decision_reason="Forwarding multi-write to PLC failed; entered FAILSAFE_HOLD.",
                )
            return bytes([0x10 | 0x80, 0x04])

        threading.Thread(target=self._update_plc_diagnostics, args=(eval_res,), daemon=True).start()

        # HIGH PRIORITY FIX 6: Audit logging
        if self.audit_logger:
            self.audit_logger.log_decision(
                requested_pump_command=u_req,
                safe_pump_command=eval_res.u_safe,
                flow=eval_res.flow,
                concentration=eval_res.concentration,
                instantaneous_ceiling=eval_res.u_max_inst,
                nominal_command=eval_res.u_nom,
                cumulative_excess_mass=eval_res.m_excess,
                defense_state=eval_res.decision.value,
                decision_reason=eval_res.reason,
            )

        return resp

    def _client_handler(self, client_sock: socket.socket) -> None:
        client_sock.settimeout(1.0)
        try:
            while self._running:
                try:
                    header = b""
                    while len(header) < 7 and self._running:
                        chunk = client_sock.recv(7 - len(header))
                        if not chunk:
                            return
                        header += chunk

                    if len(header) < 7:
                        return

                    trans_id, proto_id, length, unit_id = struct.unpack(">HHHB", header)
                    if proto_id != 0:
                        continue

                    pdu_len = length - 1
                    if pdu_len <= 0:
                        continue

                    pdu = b""
                    while len(pdu) < pdu_len and self._running:
                        chunk = client_sock.recv(pdu_len - len(pdu))
                        if not chunk:
                            return
                        pdu += chunk

                    resp_pdu = self.process_and_forward(pdu)
                    resp_len = len(resp_pdu) + 1
                    resp_header = struct.pack(">HHHB", trans_id, 0, resp_len, unit_id)
                    client_sock.sendall(resp_header + resp_pdu)

                except (socket.timeout, BlockingIOError):
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _server_loop(self) -> None:
        while self._running and self._server_socket:
            try:
                client_sock, _ = self._server_socket.accept()
                t = threading.Thread(target=self._client_handler, args=(client_sock,), daemon=True)
                t.start()
                self._client_threads.append(t)
            except (socket.timeout, BlockingIOError):
                continue
            except OSError:
                break

    def start(self) -> None:
        """Start proxy listener and telemetry polling thread."""
        if self._running:
            return

        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.listen_host, self.listen_port))
        self._server_socket.listen(10)
        self._server_socket.settimeout(0.5)

        # Initial poll to verify downstream PLC
        self._poll_plc_telemetry()
        with self._lock:
            self._last_interlock_wall_time = time.monotonic()

        self._server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self._server_thread.start()

        self._telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self._telemetry_thread.start()

    def stop(self) -> None:
        """Clean shutdown of proxy."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)
            self._server_thread = None

        if self._telemetry_thread and self._telemetry_thread.is_alive():
            self._telemetry_thread.join(timeout=1.0)
            self._telemetry_thread = None
