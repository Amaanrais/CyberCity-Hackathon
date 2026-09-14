# AquaPhy — CyberCity Hackathon

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
