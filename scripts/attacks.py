#!/usr/bin/env python3
"""
Python Attack Script & Demonstration Harness for Oldsmar Safety Interlock.

Supports:
1. Automated execution of all 4 attack variants.
2. Mutate-and-retry stealth attack: An adversarial optimizer that probes the interlock
   boundary by perturbing dosing requests to search for allowable blind spots.
3. Interactive CLI menu for live presentations.
"""

import argparse
import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000"


def print_banner():
    print("""
================================================================================
  OLDSMAR SCADA ATTACK SIMULATION HARNESS
  Demonstrating Chemical Dosing Sensor Tampering & SIS Interlock Defense
================================================================================
""")


def get_state(base_url=BASE_URL):
    try:
        r = requests.get(f"{base_url}/state", timeout=2.0)
        return r.json()
    except Exception as e:
        print(f"Error communicating with {base_url}: {e}", file=sys.stderr)
        return None


def set_interlock(enabled: bool, base_url=BASE_URL):
    requests.post(f"{base_url}/interlock", json={"enabled": enabled}, timeout=2.0)
    mode = "ENGAGED (ON)" if enabled else "BYPASSED (OFF)"
    print(f"[*] SIS Hardware Key Switch: {mode}")


def reset_system(base_url=BASE_URL):
    res = requests.post(f"{base_url}/reset", timeout=2.0).json()
    print(f"[*] System Reset Complete. Active Run ID: {res.get('run_id')}")


def run_oldsmar_spike(base_url=BASE_URL):
    print("\n[+] Triggering Attack 1: Oldsmar Spike (Primary -> 11,100 ppm)...")
    res = requests.post(f"{base_url}/attack/oldsmar_spike", timeout=2.0).json()
    print(f"    Result: {res}")


def run_single_channel_stealth(base_url=BASE_URL):
    print("\n[+] Triggering Attack 2: Single-Channel Stealth (Primary -> 135 ppm)...")
    res = requests.post(f"{base_url}/attack/single_channel_stealth", timeout=2.0).json()
    print(f"    Result: {res}")


def run_slow_ramp(base_url=BASE_URL):
    print("\n[+] Triggering Attack 3: Slow Ramp / Dual Compromise (+35 ppm/s)...")
    res = requests.post(f"{base_url}/attack/slow_ramp", timeout=2.0).json()
    print(f"    Result: {res}")


def run_flow_falsification(base_url=BASE_URL):
    print("\n[+] Triggering Attack 4: Flow Sensor Falsification (Flow -> 15 L/s)...")
    res = requests.post(f"{base_url}/attack/flow_falsification", timeout=2.0).json()
    print(f"    Result: {res}")


def stop_attacks(base_url=BASE_URL):
    print("\n[*] Stopping all active attack injections...")
    res = requests.post(f"{base_url}/attack/stop", timeout=2.0).json()
    print(f"    Result: {res}")


def mutate_and_retry_attack(base_url=BASE_URL, max_steps=20):
    """
    Simulates an intelligent adversary executing a mutate-and-retry attack:
    Iteratively injects values, senses whether they were accepted or blocked,
    and adapts its injection to skirt safety thresholds.
    """
    print("\n=== STARTING ADVERSARIAL MUTATE-AND-RETRY ATTACK ===")
    print("Goal: Test if an attacker can discover and exploit any interlock threshold.")
    reset_system(base_url)
    set_interlock(True, base_url)
    time.sleep(1.0)

    current_probe = 105.0
    step_size = 5.0

    for step in range(1, max_steps + 1):
        # Attacker injects a probed primary value
        requests.post(f"{base_url}/sensors/primary/inject", json={"value": current_probe}, timeout=2.0)
        time.sleep(1.2)  # Wait for control tick

        state = get_state(base_url)
        if not state:
            break

        last_dec = state.get("last_decision", {})
        decision = last_dec.get("decision", "UNKNOWN")
        reason = last_dec.get("reason", "")
        ph = state.get("control", {}).get("ph", 0.0)

        print(f"Step {step:>2}: Probed {current_probe:>6.1f} ppm | Decision: {decision:<7} | pH: {ph:>5.2f} | {reason[:70]}")

        if decision == "ALLOWED":
            # Push harder
            current_probe += step_size
        else:
            # Blocked! Attacker tries adapting:
            print(f"    [!] Interlock blocked probe at {current_probe:.1f} ppm! Interlock defense confirmed.")
            # Attacker backs off slightly or tries stepping down
            current_probe = max(100.0, current_probe - 2.0)

    stop_attacks(base_url)
    print("=== MUTATE-AND-RETRY ATTACK TERMINATED ===")


def main():
    parser = argparse.ArgumentParser(description="Oldsmar Cyberattack CLI Harness")
    parser.add_argument("--url", default=BASE_URL, help="Base API URL")
    parser.add_argument("--attack", choices=["oldsmar", "stealth", "ramp", "flow", "mutate", "stop", "reset"], help="Execute specific attack")
    parser.add_argument("--interlock", choices=["on", "off"], help="Set interlock key switch state")
    args = parser.parse_args()

    print_banner()

    if args.interlock:
        set_interlock(args.interlock == "on", args.url)

    if args.attack == "oldsmar":
        run_oldsmar_spike(args.url)
    elif args.attack == "stealth":
        run_single_channel_stealth(args.url)
    elif args.attack == "ramp":
        run_slow_ramp(args.url)
    elif args.attack == "flow":
        run_flow_falsification(args.url)
    elif args.attack == "mutate":
        mutate_and_retry_attack(args.url)
    elif args.attack == "stop":
        stop_attacks(args.url)
    elif args.attack == "reset":
        reset_system(args.url)
    elif not args.interlock:
        # Interactive demonstration
        print("Available actions:")
        print("  1. Run Oldsmar Spike (11,100 ppm)")
        print("  2. Run Single-Channel Stealth (135 ppm)")
        print("  3. Run Slow Ramp Dual-Compromise (+35 ppm/s)")
        print("  4. Run Flow Falsification (15 L/s)")
        print("  5. Run Adversarial Mutate-and-Retry Probe")
        print("  6. Toggle Interlock Switch (ON/OFF)")
        print("  7. Reset System to Nominal")
        print("  8. Stop Attacks")
        print("  9. Exit")

        while True:
            try:
                choice = input("\nEnter choice [1-9]: ").strip()
                if choice == "1":
                    run_oldsmar_spike(args.url)
                elif choice == "2":
                    run_single_channel_stealth(args.url)
                elif choice == "3":
                    run_slow_ramp(args.url)
                elif choice == "4":
                    run_flow_falsification(args.url)
                elif choice == "5":
                    mutate_and_retry_attack(args.url)
                elif choice == "6":
                    state = get_state(args.url)
                    current = state.get("interlock_on", True) if state else True
                    set_interlock(not current, args.url)
                elif choice == "7":
                    reset_system(args.url)
                elif choice == "8":
                    stop_attacks(args.url)
                elif choice == "9":
                    break
            except (KeyboardInterrupt, EOFError):
                break


if __name__ == "__main__":
    main()
