"""Synthetic Modbus TCP PLC for AquaPhy Water Treatment Simulation.

Implements a self-contained Modbus TCP server (FC03, FC06, FC16) holding
process telemetry and actuator setpoints for chemical dosing:
    - Register 0: Chemical dosing pump setpoint u in [0, 1] (scaled x1000)
    - Register 1: Raw water volumetric flow Q in L/s (scaled x100)
    - Register 2: Disinfectant concentration C in mg/L (scaled x100)
    - Register 3: System Status / Defense state code (0=NORMAL, 1=CLAMP_INST, 2=CLAMP_CUMUL, 3=FAILSAFE)
    - Register 4: Cumulative excess chemical mass in mg (scaled x10)
    - Register 5: Nominal baseline pump command u_nom (scaled x1000)
    - Register 6: Instantaneous safety ceiling u_max_inst (scaled x1000)
"""

from __future__ import annotations
import socket
import struct
import threading
import time
from typing import Dict, Optional, Tuple
from src.simulation.cstr import CSTRSimulation, CSTRParameters


# Register addresses
class ModbusRegisters:
    PUMP_SETPOINT = 0
    FLOW_RATE = 1
    CONCENTRATION = 2
    STATUS_CODE = 3
    CUMULATIVE_EXCESS = 4
    NOMINAL_BASELINE = 5
    INSTANTANEOUS_CEILING = 6
    TOTAL_REGISTERS = 16


# Scaling factors between engineering floats and 16-bit unsigned integer registers
PUMP_SCALE = 1000.0   # 0.400 -> 400
FLOW_SCALE = 100.0    # 10.00 L/s -> 1000
CONC_SCALE = 100.0    # 2.00 mg/L -> 200
MASS_SCALE = 10.0     # 500.0 mg -> 5000


class SyntheticPLC:
    """Standalone Modbus TCP Server simulating a water treatment PLC."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5021,
        sim: Optional[CSTRSimulation] = None,
        auto_sim: bool = False,
        time_scale: float = 1.0,
    ) -> None:
        self.host = host
        self.port = port
        self.sim = sim or CSTRSimulation()
        self.auto_sim = auto_sim
        self.time_scale = max(0.01, float(time_scale))

        self._lock = threading.Lock()
        self._registers: Dict[int, int] = {i: 0 for i in range(ModbusRegisters.TOTAL_REGISTERS)}

        # Initialize registers with nominal physical state
        self.set_pump_setpoint(0.40)
        self.set_flow_rate(self.sim.flow)
        self.set_concentration(self.sim.concentration)
        self.set_status_code(0)

        self._running = False
        self._server_socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._sim_thread: Optional[threading.Thread] = None
        self._client_threads: list[threading.Thread] = []

    # --- Register Getters and Setters (Thread-Safe) ---

    def get_register(self, address: int) -> int:
        with self._lock:
            return self._registers.get(address, 0)

    def set_register(self, address: int, value: int) -> None:
        with self._lock:
            self._registers[address] = max(0, min(65535, int(value)))

    def get_pump_setpoint(self) -> float:
        return self.get_register(ModbusRegisters.PUMP_SETPOINT) / PUMP_SCALE

    def set_pump_setpoint(self, u: float) -> None:
        u_bounded = max(0.0, min(1.0, float(u)))
        self.set_register(ModbusRegisters.PUMP_SETPOINT, int(round(u_bounded * PUMP_SCALE)))

    def get_flow_rate(self) -> float:
        return self.get_register(ModbusRegisters.FLOW_RATE) / FLOW_SCALE

    def set_flow_rate(self, q: float) -> None:
        q_val = max(0.0, float(q))
        self.set_register(ModbusRegisters.FLOW_RATE, int(round(q_val * FLOW_SCALE)))

    def get_concentration(self) -> float:
        return self.get_register(ModbusRegisters.CONCENTRATION) / CONC_SCALE

    def set_concentration(self, c: float) -> None:
        c_val = max(0.0, float(c))
        self.set_register(ModbusRegisters.CONCENTRATION, int(round(c_val * CONC_SCALE)))

    def get_status_code(self) -> int:
        return self.get_register(ModbusRegisters.STATUS_CODE)

    def set_status_code(self, code: int) -> None:
        self.set_register(ModbusRegisters.STATUS_CODE, int(code))

    def get_cumulative_excess(self) -> float:
        return self.get_register(ModbusRegisters.CUMULATIVE_EXCESS) / MASS_SCALE

    def set_cumulative_excess(self, mass: float) -> None:
        m_val = max(0.0, float(mass))
        self.set_register(ModbusRegisters.CUMULATIVE_EXCESS, int(round(m_val * MASS_SCALE)))

    def get_nominal_baseline(self) -> float:
        return self.get_register(ModbusRegisters.NOMINAL_BASELINE) / PUMP_SCALE

    def set_nominal_baseline(self, u_nom: float) -> None:
        self.set_register(ModbusRegisters.NOMINAL_BASELINE, int(round(max(0.0, min(1.0, u_nom)) * PUMP_SCALE)))

    def get_instantaneous_ceiling(self) -> float:
        return self.get_register(ModbusRegisters.INSTANTANEOUS_CEILING) / PUMP_SCALE

    def set_instantaneous_ceiling(self, u_ceil: float) -> None:
        self.set_register(ModbusRegisters.INSTANTANEOUS_CEILING, int(round(max(0.0, min(1.0, u_ceil)) * PUMP_SCALE)))

    def step_simulation(self, dt: Optional[float] = None) -> None:
        """Advance physical simulation one step and update sensor registers."""
        u = self.get_pump_setpoint()
        q = self.get_flow_rate()
        c = self.sim.step(u=u, Q=q, dt=dt)
        self.set_concentration(c)

    # --- Modbus TCP Protocol Handling ---

    def handle_modbus_pdu(self, pdu: bytes) -> bytes:
        """Process a Modbus PDU and return the response PDU."""
        if len(pdu) < 1:
            return b"\x80\x01"  # Illegal function error

        func_code = pdu[0]

        if func_code == 0x03:  # Read Holding Registers
            if len(pdu) < 5:
                return bytes([func_code | 0x80, 0x03])
            start_addr, count = struct.unpack(">HH", pdu[1:5])
            if count < 1 or count > 125 or (start_addr + count) > ModbusRegisters.TOTAL_REGISTERS:
                return bytes([func_code | 0x80, 0x02])  # Illegal data address

            byte_count = count * 2
            values = []
            with self._lock:
                for i in range(start_addr, start_addr + count):
                    values.append(self._registers.get(i, 0))

            resp = bytearray([func_code, byte_count])
            for v in values:
                resp.extend(struct.pack(">H", v))
            return bytes(resp)

        elif func_code == 0x06:  # Write Single Register
            if len(pdu) < 5:
                return bytes([func_code | 0x80, 0x03])
            addr, val = struct.unpack(">HH", pdu[1:5])
            if addr >= ModbusRegisters.TOTAL_REGISTERS:
                return bytes([func_code | 0x80, 0x02])  # Illegal data address

            self.set_register(addr, val)
            return pdu[:5]  # Echo request as response per standard

        elif func_code == 0x10:  # Write Multiple Registers (FC16)
            if len(pdu) < 6:
                return bytes([func_code | 0x80, 0x03])
            start_addr, count, byte_count = struct.unpack(">HHB", pdu[1:6])
            if count < 1 or count > 123 or byte_count != count * 2 or len(pdu) < 6 + byte_count:
                return bytes([func_code | 0x80, 0x03])
            if (start_addr + count) > ModbusRegisters.TOTAL_REGISTERS:
                return bytes([func_code | 0x80, 0x02])

            offset = 6
            with self._lock:
                for i in range(start_addr, start_addr + count):
                    val = struct.unpack(">H", pdu[offset : offset + 2])[0]
                    self._registers[i] = max(0, min(65535, val))
                    offset += 2

            return struct.pack(">BHH", func_code, start_addr, count)

        else:
            return bytes([func_code | 0x80, 0x01])  # Illegal function

    def _client_handler(self, client_sock: socket.socket) -> None:
        client_sock.settimeout(1.0)
        try:
            while self._running:
                try:
                    # Read 7-byte MBAP header
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
                        continue  # Not Modbus protocol

                    pdu_len = length - 1
                    if pdu_len <= 0:
                        continue

                    pdu = b""
                    while len(pdu) < pdu_len and self._running:
                        chunk = client_sock.recv(pdu_len - len(pdu))
                        if not chunk:
                            return
                        pdu += chunk

                    resp_pdu = self.handle_modbus_pdu(pdu)
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

    def _sim_loop(self) -> None:
        """Background physics simulation update loop."""
        last_time = time.monotonic()
        while self._running:
            now = time.monotonic()
            dt_wall = now - last_time
            last_time = now
            dt_process = dt_wall * self.time_scale
            self.step_simulation(dt=dt_process)
            sleep_sec = max(0.005, self.sim.params.dt / self.time_scale)
            time.sleep(sleep_sec)

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
        """Start the Modbus TCP server and optional simulation loop."""
        if self._running:
            return

        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(10)
        self._server_socket.settimeout(0.5)

        self._server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self._server_thread.start()

        if self.auto_sim:
            self._sim_thread = threading.Thread(target=self._sim_loop, daemon=True)
            self._sim_thread.start()

    def stop(self) -> None:
        """Stop the Modbus TCP server cleanly."""
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

        if self._sim_thread and self._sim_thread.is_alive():
            self._sim_thread.join(timeout=1.0)
            self._sim_thread = None

    @property
    def is_running(self) -> bool:
        return self._running
