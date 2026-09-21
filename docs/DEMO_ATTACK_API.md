# Demo Guide: SCADA Attack API & SIS Interlock Defense

A practical step-by-step presentation note explaining how to demonstrate the cyberattack API endpoints, observe real-time telemetry, and show the IEC 61511 Safety Instrumented System (SIS) interlock in action.

---

## 1. Quick Setup & Server Launch

Ensure the application is running locally:

```bash
# Activate your virtual environment and start the server
source .venv/bin/activate
python run.py
```

- **Dashboard UI:** [http://localhost:8000/](http://localhost:8000/)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Base API URL:** `http://127.0.0.1:8000`

---

## 2. API Endpoints Overview

| Method | Endpoint | Description | Payload Example |
|---|---|---|---|
| `POST` | `/interlock` | Stand-in for physical SIS key switch (`true`=Engaged, `false`=Bypassed) | `{"enabled": false}` |
| `POST` | `/attack/{variant}` | Trigger predefined attack vector (`oldsmar_spike`, `single_channel_stealth`, `slow_ramp`, `flow_falsification`, `stop`) | *None* |
| `POST` | `/sensors/primary/inject` | Arbitrary injection into SCADA primary sensor channel | `{"value": 11100.0}` |
| `POST` | `/sensors/verification/inject`| Arbitrary injection into secondary verification sensor channel | `{"value": 135.0}` |
| `POST` | `/sensors/flow/inject` | Arbitrary injection into water flow rate sensor | `{"value": 15.0}` |
| `POST` | `/reset` | Reset simulation, reseed RNG, clear active attacks, start new run | *None* |
| `GET` | `/state` | In-memory atomic snapshot of plant physics, control, and gates | Query: `?since_event_id=...` |
| `GET` | `/events` | Stream of live system logs & safety trip notifications | Query: `?since_id=...` |
| `GET` | `/runs` | Historical runs stored in the SQLite audit sink | *None* |
| `GET` | `/runs/{run_id}/decisions` | Forensic log of interlock decisions for a given run | Query: `?limit=50` |

---

## 3. High-Impact 3-Phase Live Demo Script

### Phase 1: Nominal Baseline Verification
Show the system running under normal operating conditions:

```bash
# 1. Ensure the safety interlock is ENGAGED
curl -s -X POST http://127.0.0.1:8000/interlock \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' | jq .

# 2. Reset the system to a clean baseline
curl -s -X POST http://127.0.0.1:8000/reset | jq .

# 3. Check live state telemetry
curl -s http://127.0.0.1:8000/state | jq '{
  interlock_on: .interlock_on,
  nominal_ppm: .control.actual_dose_ppm,
  water_pH: .control.ph,
  status: .control.status_text
}'
```
**Expected Observation:**
- pH stabilizes in the **Safe Green Band** (~7.60).
- Actual dose and requested dose overlap at ~100 ppm.
- Status displays `NOMINAL OPERATION`.

---

### Phase 2: Unprotected Attack (The "Failure Mode")
Demonstrate the catastrophic physical outcome when SCADA operates without an independent safety interlock:

```bash
# 1. BYPASS the SIS Interlock (simulate standard SCADA without safety enclave)
curl -s -X POST http://127.0.0.1:8000/interlock \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' | jq .

# 2. Trigger the Oldsmar Spike Attack (Primary sensor jump to 11,100 ppm)
curl -s -X POST http://127.0.0.1:8000/attack/oldsmar_spike | jq .
```

*Or via CLI script:*
```bash
bash scripts/attack_oldsmar.sh
```

**Live Impact to Highlight:**
- **Control Response:** Controller blindly trusts the sensor and demands ~11,100 ppm.
- **Physical Actuation:** Dosing pump ramps up to 11,100 ppm.
- **Reaction Kinetics:** Finished water pH climbs over 15–20 seconds through the amber zone into the **Caustic Red Band (pH > 10.0 to 12.8+)**.
- **Conclusion for Judges:** *"Standard SCADA authentication is useless here because the command is considered valid. Without physical interlocks, the water turns into caustic drain cleaner."*

---

### Phase 3: Active SIS Interlock Defense (The "Ghost Line")
Demonstrate how the 3-gate safety interlock mitigates the attack in real time:

```bash
# 1. Reset simulation and RE-ENGAGE the safety interlock
curl -s -X POST http://127.0.0.1:8000/reset | jq .
curl -s -X POST http://127.0.0.1:8000/interlock \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' | jq .

# 2. Launch the same Oldsmar Spike attack against the protected system
curl -s -X POST http://127.0.0.1:8000/attack/oldsmar_spike | jq .

# 3. Inspect the interlock decision record
curl -s http://127.0.0.1:8000/state | jq '.last_decision'
```

**Live Impact to Highlight:**
- **The "Ghost Line":** On the Dose chart, the **dashed red requested dose** rockets to 11,100 ppm, but the **solid cyan actual dose** stays locked safely at 100 ppm.
- **Water Chemistry Unaffected:** Water pH stays safe at ~7.60.
- **Interlock Decision:**
  ```json
  {
    "decision": "BLOCKED",
    "reason": "Hard stoichiometric bound exceeded: projected resulting concentration 11100.0 ppm > 150.0 ppm limit",
    "gate_tripped": "HARD_BOUND"
  }
  ```
- **Auditing:** Every rejected pulse is recorded to the write-only SQLite audit database.

**How the trigger works / how it resolves the attack:**
1. The attack spoofs the primary sensor to 11,100 ppm (the requested dose SCADA now believes is correct).
2. Every requested dose passes through the interlock *before* it reaches the pump actuator — SCADA cannot write to the pump directly.
3. The interlock projects the resulting finished-water concentration from that requested value (`ppm = mass / flow`), not the raw sensor reading, and checks it against gate 1's 150 ppm hard ceiling (gates 2 and 3 — slew rate and dual-channel cross-check — are evaluated the same way for the other attack vectors).
4. 11,100 ppm exceeds 150 ppm, so gate 1 trips `HARD_BOUND` and the command is rejected outright.
5. Instead of forwarding the bad command, the actuator holds the last known-safe setpoint (100 ppm) — the pump physically never moves.
6. The decision (`BLOCKED`, reason, `gate_tripped`) is written to the audit sink regardless of outcome, so there's a forensic record even though the command never took effect.

---

## 4. Demonstrating Defense-in-Depth (The Other 3 Vectors)

Run through the remaining attack vectors to prove that multiple distinct safety gates protect against subtle and coordinated adversaries.

### Vector 2: Single-Channel Stealth (`/attack/single_channel_stealth`)
- **Adversary Action:** Primary sensor set to 135 ppm (below 150 ppm hard ceiling, within 40 ppm/s slew rate).
- **Trigger:**
  ```bash
  curl -s -X POST http://127.0.0.1:8000/attack/single_channel_stealth | jq .
  # or: bash scripts/attack_stealth.sh
  ```
- **Tripped Gate:** **Gate 3: Dual-Channel Analytic Redundancy Cross-Check** (`SENSOR_DISAGREEMENT`).
- **Pitch Point:** Proves why simple min/max bounds fail and independent verification channels are mandatory.

### Vector 3: Slow Ramp Dual-Compromise (`/attack/slow_ramp`)
- **Adversary Action:** Both Primary and Verification sensors ramp slowly (+35 ppm/s) in lockstep, defeating cross-checks and rate limits.
- **Trigger:**
  ```bash
  curl -s -X POST http://127.0.0.1:8000/attack/slow_ramp | jq .
  # or: bash scripts/attack_slow_ramp.sh
  ```
- **Tripped Gate:** **Gate 1: Hard Stoichiometric Bound** (`HARD_BOUND`).
- **Pitch Point:** Proves cross-checks alone are vulnerable to sophisticated dual compromises. The hard thermodynamic ceiling is the ultimate backstop.

### Vector 4: Flow Sensor Falsification (`/attack/flow_falsification`)
- **Adversary Action:** Dosing sensors are untouched (100 ppm), but flow meter is spoofed down to 15 L/s.
- **Trigger:**
  ```bash
  curl -s -X POST http://127.0.0.1:8000/attack/flow_falsification | jq .
  # or: bash scripts/attack_flow.sh
  ```
- **Tripped Gate:** **Gate 1: Projected Concentration Check** (`HARD_BOUND`).
- **Pitch Point:** Demonstrates that the interlock checks physical resulting concentration (`ppm = mass / flow`) rather than raw pump stroke.

---

## 5. Automated Interactive Harness & Adversarial Prober

Instead of manual `curl` calls, run the automated Python demonstration utility:

```bash
# Interactive CLI Menu
python scripts/attacks.py

# Automated Adversarial Mutate-and-Retry Optimization Probe
python scripts/attacks.py --attack mutate
```

The `mutate` routine executes an intelligent adversary algorithm that systematically searches for blind spots in the interlock thresholds and displays the live rejection responses.

---

## 6. Restoring Nominal Operation

To stop attacks and restore nominal physical simulation:

```bash
curl -s -X POST http://127.0.0.1:8000/attack/stop | jq .
# or run:
bash scripts/reset.sh
```
