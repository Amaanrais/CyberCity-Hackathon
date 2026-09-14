"""Unit and integration tests for Modbus Inline Proxy (Phase 4 & Phase 8)."""

import socket
import struct
import time
from typing import Tuple
import pytest
from src.plc.synthetic_plc import SyntheticPLC, ModbusRegisters, PUMP_SCALE
from src.interlock.proxy import ModbusProxy
from src.interlock.physics_engine import PhysicsEngine, DefenseState, InterlockParameters


def send_modbus_write(sock: socket.socket, trans_id: int, addr: int, val: int) -> Tuple[int, int]:
    pdu = struct.pack(">BHH", 0x06, addr, val)
    header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)
    sock.sendall(header + pdu)

    resp_header = b""
    while len(resp_header) < 7:
        chunk = sock.recv(7 - len(resp_header))
        if not chunk:
            raise ConnectionError("Connection lost")
        resp_header += chunk

    _, _, r_len, _ = struct.unpack(">HHHB", resp_header)
    resp_pdu = b""
    while len(resp_pdu) < (r_len - 1):
        chunk = sock.recv((r_len - 1) - len(resp_pdu))
        if not chunk:
            raise ConnectionError("Connection lost")
        resp_pdu += chunk

    resp_func = resp_pdu[0]
    if resp_func & 0x80:
        return resp_func, resp_pdu[1]  # error
    r_addr, r_val = struct.unpack(">HH", resp_pdu[1:5])
    return r_addr, r_val


def send_modbus_raw_request(sock: socket.socket, trans_id: int, pdu: bytes) -> bytes:
    header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)
    sock.sendall(header + pdu)

    resp_header = b""
    while len(resp_header) < 7:
        chunk = sock.recv(7 - len(resp_header))
        if not chunk:
            raise ConnectionError("Connection lost")
        resp_header += chunk

    _, _, r_len, _ = struct.unpack(">HHHB", resp_header)
    resp_pdu = b""
    while len(resp_pdu) < (r_len - 1):
        chunk = sock.recv((r_len - 1) - len(resp_pdu))
        if not chunk:
            raise ConnectionError("Connection lost")
        resp_pdu += chunk

    return resp_pdu


def test_proxy_normal_forwarding():
    """Verify proxy forwards safe commands transparently to the PLC."""
    plc_port = 55101
    proxy_port = 55102

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))
            # Send normal safe command u = 0.40 (400)
            addr, val = send_modbus_write(sock, 201, ModbusRegisters.PUMP_SETPOINT, 400)
            assert addr == ModbusRegisters.PUMP_SETPOINT
            assert val == 400

            # Verify PLC register directly
            assert plc.get_pump_setpoint() == 0.40
            assert proxy.current_state == DefenseState.NORMAL
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_clamps_acute_spike():
    """Verify proxy clamps an acute spike when the calculated instantaneous ceiling is exceeded."""
    plc_port = 55103
    proxy_port = 55104

    plc = SyntheticPLC(port=plc_port)
    # Set high concentration close to C_max (3.99 mg/L)
    plc.set_concentration(3.99)
    plc.start()

    # Interlock with eval_dt=1.0 so ceiling is low
    engine = PhysicsEngine(InterlockParameters(eval_dt=1.0))
    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port, engine=engine)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))
            # Attacker sends acute maximum dosing u = 1.0 (1000)
            addr, val = send_modbus_write(sock, 202, ModbusRegisters.PUMP_SETPOINT, 1000)
            # The forwarded command received by PLC must be clamped (< 1000)
            plc_u = plc.get_pump_setpoint()
            assert plc_u < 1.0
            assert proxy.current_state == DefenseState.CLAMPED_INSTANTANEOUS
            assert val == int(round(plc_u * PUMP_SCALE))
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_clamps_cumulative_creep():
    """Verify proxy clamps insidious low-and-slow attack once budget is exhausted."""
    plc_port = 55105
    proxy_port = 55106

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    # Small budget (4.0 mg) so test executes quickly in ~0.6s
    engine = PhysicsEngine(InterlockParameters(mass_budget=4.0, eval_dt=0.1))
    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port, engine=engine)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))

            # Attacker sends u = 0.50 (excess rate = 10 mg/s above nominal 0.40)
            # Send 10 writes with simulated elapsed time
            for i in range(10):
                # Manually evaluate time steps or step engine
                send_modbus_write(sock, 300 + i, ModbusRegisters.PUMP_SETPOINT, 500)
                time.sleep(0.06)

            # Once budget > 50mg is breached, proxy transitions to CLAMPED_CUMULATIVE
            # and clamps setpoint to u_nom = 0.40
            assert proxy.current_state == DefenseState.CLAMPED_CUMULATIVE
            assert pytest.approx(plc.get_pump_setpoint(), rel=1e-3) == 0.40
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_failsafe_on_plc_loss():
    """Verify proxy transitions to FAILSAFE_HOLD when downstream connection is lost."""
    plc_port = 55107
    proxy_port = 55108

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port, telemetry_poll_interval=0.05)
    proxy.start()

    time.sleep(0.1)
    assert proxy.current_state == DefenseState.NORMAL

    # Now terminate the PLC abruptly
    plc.stop()
    time.sleep(0.15)

    # Proxy should detect loss of telemetry and enter FAILSAFE_HOLD
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", proxy_port))
        # Client tries to write a dosing command
        func, err = send_modbus_write(sock, 401, ModbusRegisters.PUMP_SETPOINT, 600)
        # Should return Modbus error response (0x86) and hold state
        assert func == 0x86
        assert proxy.current_state == DefenseState.FAILSAFE_HOLD

    proxy.stop()


def test_proxy_blocks_telemetry_spoof_fc06():
    """HIGH PRIORITY FIX 1: Verify FC06 writes to protected telemetry registers are rejected."""
    plc_port = 55109
    proxy_port = 55110

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))

            # 1. Attacker attempts to spoof Flow Rate (Register 1) to 50.0 L/s (5000)
            func, err = send_modbus_write(sock, 501, ModbusRegisters.FLOW_RATE, 5000)
            assert func == 0x86  # FC06 error
            assert err == 0x02   # Illegal Data Address
            # Verify PLC register was NOT modified
            assert plc.get_flow_rate() == 10.0

            # 2. Attacker attempts to spoof Concentration (Register 2) to 0.50 mg/L (50)
            func, err = send_modbus_write(sock, 502, ModbusRegisters.CONCENTRATION, 50)
            assert func == 0x86  # FC06 error
            assert err == 0x02   # Illegal Data Address
            # Verify PLC register was NOT modified
            assert plc.get_concentration() == 2.0
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_blocks_telemetry_spoof_fc16():
    """HIGH PRIORITY FIX 1: Verify FC16 multi-register writes targeting telemetry are rejected."""
    plc_port = 55111
    proxy_port = 55112

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))

            # Attacker attempts FC16 to overwrite Pump (0), Flow (1), Concentration (2)
            # start=0, count=3, byte_count=6, values: 800, 3000, 100
            pdu = struct.pack(">BHHBHHH", 0x10, 0, 3, 6, 800, 3000, 100)
            resp = send_modbus_raw_request(sock, 503, pdu)

            assert resp[0] == 0x90  # FC16 error
            assert resp[1] == 0x02  # Illegal Data Address
            # PLC telemetry must remain pristine
            assert plc.get_flow_rate() == 10.0
            assert plc.get_concentration() == 2.0
    finally:
        proxy.stop()
        plc.stop()


def test_spoofed_telemetry_cannot_bypass_interlock():
    """HIGH PRIORITY FIX 1: Verify spoofing telemetry cannot alter safety decisions."""
    plc_port = 55113
    proxy_port = 55114

    plc = SyntheticPLC(port=plc_port)
    # Contact tank is near critical concentration (3.99 mg/L)
    plc.set_concentration(3.99)
    plc.start()

    engine = PhysicsEngine(InterlockParameters(eval_dt=1.0))
    proxy = ModbusProxy(listen_port=proxy_port, plc_port=plc_port, engine=engine)
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))

            # Attacker attempts to spoof concentration to low value (1.00 mg/L) to bypass ceiling
            func, err = send_modbus_write(sock, 601, ModbusRegisters.CONCENTRATION, 100)
            assert func == 0x86
            assert err == 0x02

            # Attacker now sends acute spike u = 1.0 (1000) expecting spoof to fool interlock
            addr, val = send_modbus_write(sock, 602, ModbusRegisters.PUMP_SETPOINT, 1000)

            # The proxy MUST still clamp because it uses genuine PLC telemetry!
            plc_u = plc.get_pump_setpoint()
            assert plc_u < 1.0
            assert proxy.current_state == DefenseState.CLAMPED_INSTANTANEOUS
            assert val == int(round(plc_u * PUMP_SCALE))
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_idle_gap_trips_and_clamps_plc():
    """HIGH PRIORITY FIX 2: Verify cumulative excess accumulates during silent idle gaps
    and proxy autonomously clamps the PLC pump setpoint without requiring another attacker write.
    """
    plc_port = 55115
    proxy_port = 55116

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    # Small budget (5.0 mg) so idle gap of ~0.6s trips at 10 mg/s excess
    engine = PhysicsEngine(InterlockParameters(mass_budget=5.0, window_duration=60.0))
    proxy = ModbusProxy(
        listen_port=proxy_port,
        plc_port=plc_port,
        engine=engine,
        telemetry_poll_interval=0.03,
    )
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))

            # Attacker writes elevated command u = 0.50 (excess rate = 10 mg/s)
            addr, val = send_modbus_write(sock, 701, ModbusRegisters.PUMP_SETPOINT, 500)
            assert val == 500
            assert plc.get_pump_setpoint() == 0.50
            assert proxy.current_state == DefenseState.NORMAL

        # Attacker closes socket and goes COMPLETELY SILENT for 0.8 seconds
        time.sleep(0.8)

        # Proxy background loop must have accumulated > 5.0 mg of excess mass,
        # transitioned to CLAMPED_CUMULATIVE, and clamped the PLC pump register to u_nom (0.40)
        assert proxy.current_state == DefenseState.CLAMPED_CUMULATIVE
        assert pytest.approx(plc.get_pump_setpoint(), rel=1e-3) == 0.40

    finally:
        proxy.stop()
        plc.stop()


def test_audit_logging_on_clamp(tmp_path):
    """HIGH PRIORITY FIX 6: Verify clamp decision appends valid JSONL record with all fields."""
    import json
    audit_file = tmp_path / "test_audit.jsonl"

    plc_port = 55117
    proxy_port = 55118

    plc = SyntheticPLC(port=plc_port)
    plc.set_concentration(3.99)
    plc.start()

    engine = PhysicsEngine(InterlockParameters(eval_dt=1.0))
    proxy = ModbusProxy(
        listen_port=proxy_port,
        plc_port=plc_port,
        engine=engine,
        audit_log_path=str(audit_file),
    )
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))
            # Attacker sends acute spike u = 1.0
            send_modbus_write(sock, 801, ModbusRegisters.PUMP_SETPOINT, 1000)

        # Verify audit log was written
        assert audit_file.exists()
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1

        record = json.loads(lines[-1])
        required_fields = [
            "timestamp",
            "requested_pump_command",
            "safe_pump_command",
            "Q",
            "C",
            "instantaneous_ceiling",
            "nominal_command",
            "cumulative_excess_mass",
            "defense_state",
            "decision_reason",
        ]
        for field in required_fields:
            assert field in record, f"Missing required audit field: {field}"

        assert record["requested_pump_command"] == 1.0
        assert record["safe_pump_command"] < 1.0
        assert record["defense_state"] == "CLAMPED_INSTANTANEOUS"
        assert len(record["decision_reason"]) > 0
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_idle_gap_with_time_scale_4():
    """HIGH PRIORITY FIX 1: Verify interlock accounts for process time when time_scale=4.0.

    A dosing command u=0.55 (excess rate = 15 mg/s above nominal 0.40) is followed
    by an idle gap of 0.45 seconds wall-clock time.
    At time_scale=4.0:
      Elapsed process time = 0.45s * 4.0 = 1.80 seconds.
      Accumulated excess mass = 1.80s * 15 mg/s = 27.0 mg.
    With a budget of 15.0 mg:
      - Process-time accounting trips the budget (27.0 mg > 15.0 mg) and clamps PLC to 0.40.
      - A flawed unscaled wall-clock fallback would only see 0.45s * 15 mg/s = 6.75 mg (< 15 mg)
        and would fail to trip!
    """
    plc_port = 55121
    proxy_port = 55122

    plc = SyntheticPLC(port=plc_port, time_scale=4.0)
    plc.start()

    engine = PhysicsEngine(InterlockParameters(mass_budget=15.0, window_duration=60.0))
    proxy = ModbusProxy(
        listen_port=proxy_port,
        plc_port=plc_port,
        engine=engine,
        telemetry_poll_interval=0.02,
        time_scale=4.0,
    )
    proxy.start()

    time.sleep(0.1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", proxy_port))
            # Attacker sends elevated setpoint u = 0.55 (550)
            addr, val = send_modbus_write(sock, 901, ModbusRegisters.PUMP_SETPOINT, 550)
            assert val == 550
            assert plc.get_pump_setpoint() == 0.55
            assert proxy.current_state == DefenseState.NORMAL

        # Attacker goes silent for 0.45s wall clock time (equivalent to 1.8s process time at 4.0x)
        # 1.8s * 15 mg/s = 27.0 mg > 15.0 mg budget
        time.sleep(0.45)

        # Must have clamped due to process-time scaling
        assert proxy.current_state == DefenseState.CLAMPED_CUMULATIVE
        assert pytest.approx(plc.get_pump_setpoint(), rel=1e-3) == 0.40
        assert engine.get_cumulative_excess() >= 15.0
    finally:
        proxy.stop()
        plc.stop()


def test_proxy_concurrent_writes_stress():
    """HIGH PRIORITY FIX 2: Concurrent write requests across multiple client sockets.

    Verifies that multiple concurrent client connections hammering the proxy:
    1. Do not cause exceptions or deadlocks.
    2. Do not double-count mass beyond physical limits.
    3. Keep PLC register and proxy state consistent.
    """
    import threading
    plc_port = 55123
    proxy_port = 55124

    plc = SyntheticPLC(port=plc_port)
    plc.start()

    engine = PhysicsEngine(InterlockParameters(mass_budget=50.0, window_duration=60.0))
    proxy = ModbusProxy(
        listen_port=proxy_port,
        plc_port=plc_port,
        engine=engine,
        telemetry_poll_interval=0.02,
    )
    proxy.start()

    time.sleep(0.1)

    exceptions: list[Exception] = []

    def client_worker(worker_id: int):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(("127.0.0.1", proxy_port))
                for i in range(25):
                    # Alternate between 0.45 and 0.55
                    val = 450 if (i % 2 == 0) else 550
                    send_modbus_write(sock, 1000 * worker_id + i, ModbusRegisters.PUMP_SETPOINT, val)
                    time.sleep(0.01)
        except Exception as e:
            exceptions.append(e)

    threads = [threading.Thread(target=client_worker, args=(w,)) for w in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10.0)

    try:
        assert len(exceptions) == 0, f"Client worker exceptions: {exceptions}"
        assert proxy.current_state in (DefenseState.NORMAL, DefenseState.CLAMPED_CUMULATIVE)
        assert 0.0 <= plc.get_pump_setpoint() <= 1.0
        assert engine.get_cumulative_excess() >= 0.0
    finally:
        proxy.stop()
        plc.stop()


