"""Tests for Synthetic Modbus TCP PLC (Phase 2)."""

import socket
import struct
import time
import pytest
from src.plc.synthetic_plc import SyntheticPLC, ModbusRegisters, PUMP_SCALE, FLOW_SCALE, CONC_SCALE


def send_modbus_request(sock: socket.socket, trans_id: int, pdu: bytes) -> bytes:
    """Helper to send MBAP header + PDU and return response PDU."""
    header = struct.pack(">HHHB", trans_id, 0, len(pdu) + 1, 1)
    sock.sendall(header + pdu)

    resp_header = b""
    while len(resp_header) < 7:
        chunk = sock.recv(7 - len(resp_header))
        if not chunk:
            raise ConnectionError("Socket closed")
        resp_header += chunk

    r_trans_id, r_proto, r_len, r_unit = struct.unpack(">HHHB", resp_header)
    assert r_trans_id == trans_id
    assert r_proto == 0

    resp_pdu = b""
    pdu_len = r_len - 1
    while len(resp_pdu) < pdu_len:
        chunk = sock.recv(pdu_len - len(resp_pdu))
        if not chunk:
            raise ConnectionError("Socket closed")
        resp_pdu += chunk

    return resp_pdu


def test_synthetic_plc_modbus_tcp_lifecycle():
    """Verify Synthetic PLC starts, responds to Modbus TCP requests, and shuts down cleanly."""
    port = 55021  # Non-privileged test port
    plc = SyntheticPLC(port=port)
    plc.start()
    assert plc.is_running

    time.sleep(0.05)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", port))
            sock.settimeout(2.0)

            # 1. Read holding registers 0..3 (FC03)
            # Starting address 0, count 4
            read_req = struct.pack(">BHH", 0x03, 0, 4)
            resp = send_modbus_request(sock, 101, read_req)
            assert resp[0] == 0x03
            assert resp[1] == 8  # 4 registers * 2 bytes
            u_raw, q_raw, c_raw, status_raw = struct.unpack(">HHHH", resp[2:10])
            assert u_raw == 400  # 0.40 * 1000
            assert q_raw == 1000 # 10.0 * 100
            assert c_raw == 200  # 2.00 * 100
            assert status_raw == 0

            # 2. Write single register (FC06): set pump to 0.75 (750)
            write_req = struct.pack(">BHH", 0x06, ModbusRegisters.PUMP_SETPOINT, 750)
            resp = send_modbus_request(sock, 102, write_req)
            assert resp == write_req  # Echo
            assert pytest.approx(plc.get_pump_setpoint(), rel=1e-3) == 0.75

            # 3. Read back pump setpoint to verify persistence
            read_req = struct.pack(">BHH", 0x03, 0, 1)
            resp = send_modbus_request(sock, 103, read_req)
            assert resp[0] == 0x03
            u_val = struct.unpack(">H", resp[2:4])[0]
            assert u_val == 750

            # 4. Write multiple registers (FC16): set pump=600, flow=1500
            write_multi_req = struct.pack(">BHHBHH", 0x10, 0, 2, 4, 600, 1500)
            resp = send_modbus_request(sock, 104, write_multi_req)
            assert resp[0] == 0x10
            assert plc.get_pump_setpoint() == 0.60
            assert plc.get_flow_rate() == 15.0

    finally:
        plc.stop()
        assert not plc.is_running


def test_synthetic_plc_simulation_stepping():
    """Verify stepping simulation via PLC updates concentration register."""
    plc = SyntheticPLC(port=55022)
    assert plc.get_concentration() == 2.0
    assert plc.get_pump_setpoint() == 0.40

    # Increase pump setpoint to 0.80
    plc.set_pump_setpoint(0.80)
    # Step simulation 100 times (10s)
    for _ in range(100):
        plc.step_simulation(dt=0.1)

    assert plc.get_concentration() > 2.0
