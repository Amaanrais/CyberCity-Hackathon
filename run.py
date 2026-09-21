#!/usr/bin/env python3
"""
Single-command runner for the Oldsmar SCADA Safety Interlock Demo System.
Starts the FastAPI backend, static file server, SQLite audit sink, and 1Hz physical simulation.
"""

import argparse
import os
import sys
import uvicorn


def print_banner(host: str, port: int):
    print("=" * 80)
    print("  AQUALOCK SIS // MUNICIPAL WATER SCADA SAFETY INSTRUMENTED SYSTEM")
    print("  IEC 61511 Out-of-Band Cyber-Physical Chemical Interlock Defense")
    print("=" * 80)
    print(f"  * Control Room Console Dashboard: http://localhost:{port}/")
    print(f"  * REST API & Telemetry Endpoint:  http://localhost:{port}/state")
    print(f"  * Interactive OpenAPI Swagger:   http://localhost:{port}/docs")
    print("-" * 80)
    print("  DEMO ATTACK VECTORS:")
    print(f"  1. Oldsmar Spike (11,100 ppm):   bash scripts/attack_oldsmar.sh {port}")
    print(f"  2. Single-Channel Stealth:       bash scripts/attack_stealth.sh {port}")
    print(f"  3. Slow Ramp Dual Compromise:    bash scripts/attack_slow_ramp.sh {port}")
    print(f"  4. Flow Sensor Falsification:    bash scripts/attack_flow.sh {port}")
    print(f"  5. Reset System Simulation:      bash scripts/reset.sh {port}")
    print(f"  6. Python Adversarial Harness:   python scripts/attacks.py")
    print("=" * 80)
    print("  Press Ctrl+C to terminate cleanly.\n")


def get_available_port(default_port=8000):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', default_port)) != 0:
            return default_port
    return 8080


def main():
    parser = argparse.ArgumentParser(description="Start Oldsmar SCADA Interlock Demo")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: auto 8000 or 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reloading for development")
    args = parser.parse_args()

    port = args.port if args.port is not None else get_available_port(8000)
    print_banner(args.host, port)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
