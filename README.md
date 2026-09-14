# AquaPhy

**Cyber-Physical Water Safety — Hackathon Prototype**

AquaPhy prevents unsafe chemical-dosing commands from reaching a water-treatment PLC by validating them against a physical safety envelope.

**IACyC 2026 · CyberMACS Student Hackathon**
**Track:** Track A — Resilience Under Attack

---

## Project

**AquaPhy** — Inline Physical Safety Interlock for Legacy Water Treatment.

## Defender

Municipal Water Treatment Authority OT Systems Engineer / Plant Operations Supervisor.

## Threat

An adversary with Modbus TCP network connectivity manipulates chemical-dosing commands sent to a water-treatment PLC (via acute setpoint jumps or stealthy low-and-slow ramps).

## One-Sentence Capability

> AquaPhy prevents unsafe chemical-dosing commands from reaching a water-treatment PLC by validating them against a physical safety envelope.

## Core Philosophy

AquaPhy is an **active inline interlock** (bump-in-the-wire proxy), not a passive IDS. It deterministically validates and clamps unsafe Modbus commands in-flight using a dual-horizon physics engine (Instantaneous Safety Envelope + Cumulative Physical Dose-Deviation Tracker).

---

## Architecture

```
SCADA / Attacker
       ↓
AquaPhy Inline Interlock
       ↓
Synthetic PLC / Actuator
```

AquaPhy uses:

- Instantaneous physics safety limits
- Physics-derived dosing baseline
- Cumulative excess-mass limits
- Deterministic command clamping
- Failsafe hold on PLC communication loss

## Demo Flow

`THREAT` → `ATTACK (Surge & Slow-Ramp)` → `INLINE DETECTION` → `DETERMINISTIC CLAMPING` → `CONTINUOUS WATER SAFETY`

### Demo Results

| Scenario | Behavior |
|---|---|
| Normal | 40% → 40% |
| Acute attack | 100% → 80% |
| Flow surge | 56% accepted |
| Slow creep | 55% → 40% |
| Failsafe | PLC loss → `FAILSAFE_HOLD` |

---

## Run

```bash
git clone https://github.com/Amaanrais/CyberCity-Hackathon.git
cd CyberCity-Hackathon

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Run tests:**

```bash
.venv/bin/pytest -q
```

**Run the interactive demo:**

```bash
.venv/bin/python3 demo/run_demo.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), then click **RUN LIVE DEMO**.

---

## Repository Structure

```
src/simulation/        CSTR process model
src/plc/                Synthetic PLC
src/interlock/          Physics engine + inline proxy
src/ui/                 Dashboard
demo/                   Attack scripts + demo runner
tests/                  Automated tests
docs/                   Architecture + decisions
data/                   Synthetic datasets and calibration profiles
.agents/                Antigravity agent configuration and roles
```

### `docs/` — Project reasoning, threat model, architecture, and design decisions

- `docs/problem.md` — Defender profile, threat model, and capability scope.
- `docs/architecture.md` — Full mathematical derivations, parameters, and system pipeline.
- `docs/decisions.md` — Architectural decision log and trade-off rationales.

---

> **Note:** Hackathon prototype only — all process data and PLCs are synthetic.
Cyber-Physical Water Safety — Hackathon Prototype

AquaPhy prevents unsafe chemical-dosing commands from reaching a water-treatment PLC by validating them against a physical safety envelope.

Track: A — Resilience Under Attack

Architecture
SCADA / Attacker
       ↓
AquaPhy Inline Interlock
       ↓
Synthetic PLC / Actuator

AquaPhy uses:

Instantaneous physics safety limits
Physics-derived dosing baseline
Cumulative excess-mass limits
Deterministic command clamping
Failsafe hold on PLC communication loss
Demo
Normal        40% → 40%
Acute attack  100% → 80%
Flow surge    56% accepted
Slow creep    55% → 40%
Failsafe      PLC loss → FAILSAFE_HOLD
Run
git clone https://github.com/Amaanrais/CyberCity-Hackathon.git
cd CyberCity-Hackathon

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Run tests:

.venv/bin/pytest -q

Run the interactive demo:

.venv/bin/python3 demo/run_demo.py

Open:

http://127.0.0.1:8080

Then click RUN LIVE DEMO.

Project Structure
src/simulation/        CSTR process model
src/plc/               Synthetic PLC
src/interlock/         Physics engine + inline proxy
src/ui/                Dashboard
demo/                  Attack scripts + demo runner
tests/                 Automated tests
docs/                   Architecture + decisions

Hackathon prototype only — all process data and PLCs are synthetic.**IACyC 2026 · CyberMACS Student Hackathon**  
**Track:** Track A — Resilience Under Attack

---

## Project
**AquaPhy** — Inline Physical Safety Interlock for Legacy Water Treatment.

## Defender
Municipal Water Treatment Authority OT Systems Engineer / Plant Operations Supervisor.

## Threat
An adversary with Modbus TCP network connectivity manipulates chemical-dosing commands sent to a water-treatment PLC (via acute setpoint jumps or stealthy low-and-slow ramps).

## One-Sentence Capability
"AquaPhy prevents unsafe chemical-dosing commands from reaching a water-treatment PLC by validating them against a physical safety envelope."

## Core Philosophy
AquaPhy is an **active inline interlock** (bump-in-the-wire proxy), not a passive IDS. It deterministically validates and clamps unsafe Modbus commands in-flight using a dual-horizon physics engine (Instantaneous Safety Envelope + Cumulative Physical Dose-Deviation Tracker).

## Demo Flow
`THREAT` → `ATTACK (Surge & Slow-Ramp)` → `INLINE DETECTION` → `DETERMINISTIC CLAMPING` → `CONTINUOUS WATER SAFETY`

## Repository Structure
- `docs/` — Project reasoning, threat model, architecture, and design decisions:
  - `docs/problem.md` — Defender profile, threat model, and capability scope.
  - `docs/architecture.md` — Full mathematical derivations, parameters, and system pipeline.
  - `docs/decisions.md` — Architectural decision log and trade-off rationales.
- `data/` — Synthetic datasets and calibration profiles.
- `src/` — Interlock proxy, synthetic PLC, and CSTR physics engine.
- `tests/` — Unit tests for physics derivations, Modbus proxying, and clamping logic.
- `demo/` — Deterministic, repeatable attack-defense demonstration scripts.
- `.agents/` — Antigravity agent configuration and roles.
