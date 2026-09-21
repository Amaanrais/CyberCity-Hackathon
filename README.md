# AquaLock SIS — Cyber-Physical Water Treatment Safety Interlock

> 🏆 **1st Place Winner — CyberMACS "Defend What Matters" Student Hackathon (Istanbul)**  
> **Track:** Track A — Resilience Under Attack  
> **Team:** PUREIT  
> **Project Deck:** [docs/PUREIT_Presentation.pptx](docs/PUREIT_Presentation.pptx) · **Team Sheet:** [docs/Teamsheet.pdf](docs/Teamsheet.pdf)  
> **Official Hackathon Submission:** [github.com/devded/i1](https://github.com/devded/i1)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=FastAPI&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.14](https://img.shields.io/badge/Python-3.14+-blue.svg)](https://www.python.org/)
[![Safety Standard](https://img.shields.io/badge/Standard-IEC%2061511%20%2F%20ISA--84-orange.svg)]()
[![Design System](https://img.shields.io/badge/UI-Monochrome%20Industrial-black.svg)]()
[![Hackathon](https://img.shields.io/badge/CyberMACS%202026-1st%20Place%20Winner-gold.svg)]()

**AquaLock SIS** is a high-fidelity cyber-physical demonstration system showing how an out-of-band water treatment safety instrumented system (SIS) defends against SCADA sensor tampering and lethal chemical overdosing attacks. Inspired by the **February 2021 Oldsmar, Florida water treatment plant cyberattack**, in which remote adversaries manipulated sodium hydroxide (NaOH / lye) dosing from ~100 ppm to a caustic ~11,100 ppm.

---

## 1. Executive Summary & Physical Consequence

In water treatment, chemical dose alone means nothing without physical consequence. In drinking water distribution, sodium hydroxide (NaOH) is dosed to neutralize acidity and protect piping against corrosion. However:
- **Nominal Dosage (~100 ppm):** Finished water pH stabilizes in the **Safe Band (6.5 – 8.5)**.
- **Elevated Dosage (150 – 250 ppm):** Buffer capacity is exhausted; pH enters the **Elevated Band (8.5 – 10.0)**.
- **Caustic Overdose (1,000 – 11,100 ppm):** Strong base dissociation overwhelms the water; pH climbs past **10.0 to 12.8+**, transforming tap water into a corrosive drain-cleaner capable of severe chemical burns to human skin and mucous membranes.

This system demonstrates the attack succeeding when the safety interlock is **OFF** (watching pH climb into the dangerous red band over ~20 seconds), and being actively blocked when the interlock is **ON** (where the "Ghost Line" requested dose shoots into the stratosphere while the physical actuator stays locked at the safe baseline).

---

## 2. System Architecture

```
                                  +---------------------------------------+
                                  |         ADVERSARIAL ATTACK            |
                                  |  - Oldsmar Spike (11,100 ppm)         |
                                  |  - Single-Channel Stealth (135 ppm)   |
                                  |  - Slow Ramp Dual (+35 ppm/s)         |
                                  |  - Flow Falsification (15 L/s)        |
                                  +-------------------+-------------------+
                                                      |
                                                      v
+---------------------------------------------------------------------------------------------------+
| SENSOR SIMULATOR (Reproducible Seeded RNG)                                                        |
|   [Primary Channel]       ~100 ppm NaOH + Gaussian Noise  (Attack Surface fed to SCADA)           |
|   [Verification Channel] ~100 ppm NaOH + Gaussian Noise  (Independent Channel, NEVER drives pump)|
|   [Water Flow Rate]      ~50 L/s (Input with noise; unmanaged environmental variable)             |
+-------------------+---------------------------------+---------------------------------------------+
                    |                                 |
                    | (Primary Sensor Reading)        | (Verification Channel)
                    v                                 |
+------------------------------------+                |
| SCADA CONTROL LOOP (1Hz)           |                |
|   Proportional Feedforward Tracker |                |
|   Emits: REQUESTED DOSE            |                |
+-------------------+----------------+                |
                    |                                 |
                    +-----------------------+         |
                                            v         v
+---------------------------------------------------------------------------------------------------+
| SAFETY INSTRUMENTED SYSTEM (SIS) INTERLOCK (IEC 61511 / ISA-84)                                   |
|   Hardware Key Switch: ON / OFF Toggle (Stand-in for air-gapped physical key switch)              |
|                                                                                                   |
|   GATE 1: HARD BOUND CEILING                                                                      |
|     Checks projected resulting concentration <= 150.0 ppm (NOT raw pump stroke).                 |
|     Immune to flow sensor spoofing and dual-compromise attacks.                                   |
|                                                                                                   |
|   GATE 2: RATE OF CHANGE (SLEW RATE) LIMIT                                                        |
|     Rejects command deltas > 40.0 ppm/s from last accepted dose.                                  |
|                                                                                                   |
|   GATE 3: DUAL-CHANNEL ANALYTIC REDUNDANCY CROSS-CHECK                                            |
|     Relative difference |P - V| / V must be <= 15%. Debounced over 2-3 samples.                   |
|                                                                                                   |
|   FAIL-SAFE DECAY POLICY                                                                          |
|     After N=5 consecutive blocks, decays dose toward nominal 100 ppm baseline.                    |
+-------------------------------------------+-------------------------------------------------------+
                                            |
                                            | (Permitted ACTUAL DOSE)
                                            v
+---------------------------------------------------------------------------------------------------+
| PHYSICAL PLANT MODEL & REACTION KINETICS                                                          |
|   Mass Feed Rate:      feed_rate_mg_s = actual_dose * actual_flow                                 |
|   Resulting Pipe Conc: resulting_ppm = feed_rate_mg_s / actual_flow                               |
|   Contact Tank Lag:    dC_tank / dt = (resulting_ppm - C_tank) / tau (tau = 4.5s, ~20s ramp)     |
|   Finished Water pH:   Buffered titration curve (Safe: 6.5-8.5 | Elevated: 8.5-10 | Danger: >10)   |
+-------------------+-------------------------------------------------------------------------------+
                    |
                    v
+---------------------------------------------------+     +-----------------------------------------+
| IN-MEMORY LIVE STATE MANAGER                      |     | WRITE-ONLY SQLITE AUDIT SINK            |
|   - Rolling deques (maxlen=90)                    |     |   - Dedicated async queue worker        |
|   - Zero-disk /state polling (every 500ms)        |     |   - Append-only decisions table         |
|   - Preserved across UI refreshes                 |     |   - Isolated from loop & UI latency     |
+---------------------------------------------------+     +-----------------------------------------+
```

---

## 3. The 4 Cyberattack Vectors

| # | Attack Variant | Adversary Action | Gates Bypassed | Tripped Gate | Physical Significance |
|---|---|---|---|---|---|
| **1** | **Oldsmar Spike** | Primary jumps 100 &rarr; 11,100 ppm | *None* | **Hard Bound + Rate of Change + Cross-Check** | Mirrors exact 2021 Oldsmar incident. Tripped on all three layers. |
| **2** | **Single-Channel Stealth** | Primary raised moderately to 135 ppm | Rate of Change (&le;40 ppm/s)<br>Hard Bound (&le;150 ppm) | **Cross-Check (Sensor Disagreement)** | Proves why single-channel bounds fail and why independent verification is vital. |
| **3** | **Slow Ramp / Dual-Compromise** | Ramps Primary & Verification +35 ppm/s together | Cross-Check (0% diff)<br>Rate of Change (+35 &le; 40) | **Hard Bound (&gt;150 ppm)** | Strongest vector: proves that cross-checks alone are insufficient against sophisticated adversaries. The physical hard bound is the ultimate backstop. |
| **4** | **Flow Sensor Falsification** | Chemical sensors untouched; Flow reported at 15 L/s | Cross-Check (100 vs 100)<br>Rate of Change (if ramped) | **Hard Bound on Resulting PPM** | Demonstrates why the interlock verifies *physical concentration* rather than raw pump displacement commands. |

---

## 4. Key Design Decisions & Judge Q&A Guide

### Q1: "What stops the attacker from just calling `/interlock` and disabling the safety system?"
> **Answer:** In actual industrial critical infrastructure adhering to **IEC 61511 / ISA-84**, Safety Instrumented Systems (SIS) are **physically air-gapped and hardwired** from the basic process control system (BPCS/SCADA). The safety logic runs on separate SIL-3 rated hardware (such as a Triconex or HIMA logic solver) housed in a locked physical control cabinet. The ON/OFF toggle in this dashboard is explicitly documented and styled as a **demo stand-in for a physical, key-operated selector switch on that cabinet**, not a reachable network endpoint.

### Q2: "Why not simply hold the last accepted dose indefinitely on a block?"
> **Answer (Fail-Safe Decay Rationale):** Holding the last accepted safe command is appropriate for transient anomalies or short-lived sensor dropouts. However, if the plant was already operating at an elevated dosing state (e.g. 140 ppm) when an attack commenced, holding that state indefinitely leaves the water quality near safety margins during a prolonged outage. Our interlock implements a deterministic **fail-safe decay**: after **5 consecutive blocked cycles**, the controller actively decays the dosing setpoint down toward the nominal **100.0 ppm baseline** via exponential filtering.

### Q3: "Why is the hard bound placed on resulting ppm instead of raw pump dose?"
> **Answer:** If the safety interlock only monitored pump stroke or motor RPM, an attacker who spoofed the raw water flow meter down to 15 L/s would cause a controller attempting mass balance to heavily overdose each litre of water. By evaluating the **projected resulting finished water concentration (`ppm = feed_mg_s / flow`)**, the interlock defends against both sensor spoofing and flow manipulation.

---

## 5. Control Room Console (shadcn/ui Dark Design)

The frontend is built with pure **HTML5, vanilla CSS custom properties, and modern JavaScript with Chart.js 4.4 + annotation plugin**. No React or build tools are required.
- **Visual Tokens:** Complete shadcn/ui token set on `:root` (`--background`, `--card`, `--primary`, `--destructive`, `--warning`, `--success`, `--border`, `--radius`).
- **One-Screen, Zero-Scrolling Layout:** Engineered for projection and presentation monitors (`height: 100vh; overflow: hidden;`).
- **Tabular Numerals:** `font-variant-numeric: tabular-nums` on all telemetry to eliminate number jittering.
- **Fixed Y-Axes:** Scales are pinned (`pH: 6.0 - 13.5`, `Dose: 0 - 12,000`, `Sensors: 0 - 12,000`) so line spikes snap with visual drama rather than being squashed by auto-scaling.
- **The "Ghost Line" (Dose Chart):** The requested dose appears as a semi-transparent dashed red line (`#ef4444`), while the actual pump dose appears as a solid cyan line (`#38bdf8`). When blocked, the red line rockets into the stratosphere while the blue line stays flat.
- **Sustained Block Choreography:** On a safety block, the entire viewport border illuminates with a red perimeter glow (`rgba(239, 68, 68, 0.45)`) that persists for 3 seconds before smoothly decaying.

---

## 6. Getting Started

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Modern web browser (Chrome, Firefox, Edge, Safari)

### Quick Start (One Command)
```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the full system
python run.py
```

Open your browser to: **[http://localhost:8000/](http://localhost:8000/)**

---

## 7. Running the Demo for Judges (3-Minute Script)

Follow this sequence for an impactful live demonstration:

1. **Nominal State (30s):**
   - Point out the dark control-room console, tabular live telemetry readouts, and the three charts.
   - Show that Primary and Verification sensor lines overlap closely around 100 ppm, pH sits safely at ~7.60 (Green Band), and the status pill shows `NOMINAL OPERATION`.
   - Point out the **SIS Key Switch** in the top center set to `ENGAGED`.

2. **The Unprotected Attack (45s):**
   - Click the **SIS Safety Interlock Switch** to toggle it **OFF** (`BYPASSED`).
   - Click **1. Oldsmar Spike (11,100 ppm)** (or run `bash scripts/attack_oldsmar.sh`).
   - Watch the requested and actual dose lines shoot together to ~11,100 ppm.
   - Watch the finished water pH climb from 7.6 through the amber zone and into the dangerous red caustic band (>10.0, reaching 12.8+). The status pill flashes `CRITICAL DANGER`.
   - Explain: *"Without an independent safety interlock, the SCADA controller trusts the tampered sensor and poisons the finished water."*

3. **The Protected Defense & The "Ghost Line" (45s):**
   - Click **↺ Reset System Simulation** and toggle the **SIS Safety Interlock Switch** back **ON** (`ENGAGED`).
   - Click **1. Oldsmar Spike (11,100 ppm)** again.
   - **Observe the Block Choreography:**
     - The screen border flashes red.
     - The status pill transitions to `DOSE BLOCKED: SENSOR_DISAGREEMENT`.
     - In the Dose Chart, the **dashed red requested dose** rockets to 11,100 ppm, while the **solid blue actual dose** remains flat at 100 ppm.
     - In the pH Chart, the water line remains completely flat and safe at 7.60.
     - In the Event Log, a red badge slides in with the exact safety gate trip reason.

4. **Layered Defense-in-Depth (60s):**
   - Click **2. Single-Channel Stealth (135 ppm)** &rarr; show it caught exclusively by channel cross-check.
   - Click **3. Slow Ramp Dual (+35 ppm/s)** &rarr; show both channels ramping together, defeating cross-check and rate-of-change, but stopped cold by the 150 ppm hard ceiling.
   - Click **4. Flow Falsification (15 L/s)** &rarr; show that manipulating flow to trick the controller is blocked because the interlock checks physical concentration.

---

## 8. CLI & Attack Automation

You can also trigger attacks from the command line while the dashboard is open:

```bash
# Bash + cURL Attack Scripts
bash scripts/attack_oldsmar.sh      # Variant 1: Oldsmar Spike
bash scripts/attack_stealth.sh      # Variant 2: Single-Channel Stealth
bash scripts/attack_slow_ramp.sh    # Variant 3: Slow Ramp Dual Compromise
bash scripts/attack_flow.sh         # Variant 4: Flow Sensor Falsification
bash scripts/reset.sh               # Reset to nominal baseline

# Interactive Python Attack Harness & Mutate-and-Retry Prober
python scripts/attacks.py           # Interactive CLI menu
python scripts/attacks.py --attack mutate  # Adversarial probing loop
```

---

## 9. Verification & Automated Test Suite

Run the full automated pytest suite:
```bash
PYTHONPATH=. .venv/bin/pytest -v
```

Test coverage includes:
- **`tests/test_plant.py`:** Chemical lag kinetics, baseline stability, and logarithmic caustic pH titration across safe, elevated, and dangerous bands.
- **`tests/test_interlock.py`:** Hard bound ceiling, slew rate limits, dual-channel debounce filter, fail-safe decay, and key switch bypass.
- **`tests/test_api.py`:** End-to-end HTTP API contracts, state snapshots, attack injection endpoints, and SQLite audit queries.

---

## 10. Technology Stack

- **Backend:** Python 3.14, FastAPI, Uvicorn, Pydantic v2
- **Persistence:** In-Memory Circular Buffers (Live State) + SQLite3 (Write-Only Audit Sink via Async Worker)
- **Frontend:** Plain HTML5, Modern CSS3 with shadcn/ui design tokens, Vanilla JavaScript (ES6)
- **Charting:** Chart.js 4.4.4 + chartjs-plugin-annotation 3.0.1 (bundled locally for 100% offline hackathon execution)
- **Testing:** Pytest, Pytest-Asyncio, HTTPX

---

## 11. Team PUREIT & Acknowledgements

This project was built and presented collaboratively at the **CyberMACS "Defend What Matters" Student Hackathon** in Istanbul:

* **Amaan Rais** — Architecture, Physical Interlock Design & Core System Implementation ([GitHub](https://github.com/Amaanrais))
* **Amar Kumar Mandal** — ICS Threat Modeling & Defense Validation
* **Mahdi Mohammad Shibli** — Control Loops & Industrial Standards Analysis
* **Quazi Fariha Tasnim** — Scenario Design & Operational Defender Persona
* **S M Dedar Alam** — Web Console, Live Presentation & Demo Orchestration ([GitHub](https://github.com/devded))

Special thanks to the judges, mentors, and organizers of the CyberMACS Hackathon for hosting an exceptional critical infrastructure cybersecurity challenge.
