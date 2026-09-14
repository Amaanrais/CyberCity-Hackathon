# AquaPhy — Problem Definition & Threat Model

**Project:** AquaPhy — Inline Physical Safety Interlock for Legacy Water Treatment  
**Track:** Track A — Resilience Under Attack  
**Version:** 1.0 (Hackathon Architecture Specification)

---

## 1. Defender Profile

* **Persona:** Municipal Water Treatment Authority OT Systems Engineer / Plant Operations Supervisor.
* **Operational Responsibility:** Ensuring continuous secondary disinfection (chlorination) of municipal drinking water while preventing chemical over-dosing that violates EPA/regulatory water safety limits or endangers public health.
* **Operational Environment:**
  * Distributed municipal water distribution network.
  * Legacy Operational Technology (OT) infrastructure: Programmable Logic Controllers (PLCs), Remote Terminal Units (RTUs), and SCADA HMIs communicating over unauthenticated industrial protocols (Modbus TCP).
  * Air-gap erosion: SCADA systems connected via enterprise IT/OT DMZs, remote maintenance cellular modems, or shared engineering workstations.

---

## 2. Threat Model & Adversary Capabilities

### 2.1 Threat Vector
An adversary has achieved network-level access to the OT control subnet (via compromised SCADA engineering workstation, weak DMZ VPN, or malicious insider). The adversary possesses the capability to issue unauthenticated Modbus TCP commands directly to the field PLC controlling chemical dosing pumps.

```
+-------------------------------------------------------------+
|                     ADVERSARY / SCADA                       |
|  - Compromised HMI / Engineering Workstation                |
|  - Capable of arbitrary Modbus TCP Function Code 06/16      |
+-------------------------------------------------------------+
                              |
                              | Modbus TCP (Holding Register write)
                              v
+-------------------------------------------------------------+
|                      AQUAPHY INTERLOCK                      |
|  - Inline proxy intercepting raw actuator setpoints         |
|  - Evaluates physics against process telemetry              |
|  - Clamps or passes validated Modbus commands               |
+-------------------------------------------------------------+
                              |
                              | Clamped / Validated Modbus TCP
                              v
+-------------------------------------------------------------+
|                        SYNTHETIC PLC                        |
|  - Standard Modbus server controlling chemical dosing pump  |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                   CSTR PROCESS SIMULATION                   |
|  - Disinfection contact tank (flow Q, concentration C)      |
+-------------------------------------------------------------+
```

### 2.2 Attack Vectors
The adversary targets the water treatment chemical dosing pump (e.g., sodium hypochlorite feed) using two distinct strategies:

1. **Attack 1: Acute Setpoint Jump (Instantaneous Attack)**
   * *Mechanism:* The adversary abruptly writes an extreme dosing command (e.g., jumping pump stroke from nominal 40% to 100%).
   * *Consequence:* Rapid surge in chemical concentration, causing disinfectant levels in the effluent to breach the maximum residual disinfectant level ($C_{max} = 4.0\text{ mg/L}$), threatening acute toxicity or pipe corrosion.
   * *Detection & Interception:* Caught by AquaPhy's **Instantaneous Safety Envelope**.

2. **Attack 2: Insidious Low-and-Slow Ramp (Cumulative Drift Attack)**
   * *Mechanism:* The adversary increases dosing setpoints by minuscule increments (e.g., +0.2% per second or small step jumps). Each individual command falls safely below instantaneous limits and rate-of-change thresholds.
   * *Consequence:* Over minutes, the cumulative chemical mass injected significantly exceeds process requirements, exhausting chemical reserves, degrading water quality, and creating stealthy over-concentration without triggering single-point threshold alarms.
   * *Detection & Interception:* Caught by AquaPhy's **Cumulative Dose-Deviation Tracker**.

---

## 3. Core Capability & One-Sentence Scope

> **"AquaPhy prevents unsafe chemical-dosing commands from reaching a water-treatment PLC by validating them against a physical safety envelope."**

AquaPhy is an **active inline interlock**, not a passive Intrusion Detection System (IDS).

---

## 4. Why an Active Inline Interlock (vs. Passive IDS)?

| Attribute | Passive IDS (e.g., Zeek, Suricata, Passive OT IDS) | AquaPhy Inline Physical Interlock |
| :--- | :--- | :--- |
| **Network Position** | SPAN port / Tap / Mirror port (out-of-band) | In-line bump-in-the-wire proxy (actuation path) |
| **Intervention Ability** | Detection only (alerts after packet reached PLC) | Deterministic prevention (validates *before* PLC executes) |
| **Physical Reality** | Chemical already pumped into contact tank before alert is triaged | Chemical command is clamped or blocked in-flight |
| **False-Positive Impact** | High alarm fatigue for human operators | Transparent clamping to physical safety boundary; process continues safely |
| **Adversary Resilience** | Bypassable if adversary cuts alert channel | Attacker commands cannot bypass the interlock physically |

**Key Insight:** In physical chemical processes, once excess sodium hypochlorite or chlorine gas is injected into the water stream, it cannot be un-injected. The reaction occurs immediately. Passive detection is fundamentally inadequate for irreversible physical harm. Defense requires an inline physical safety barrier.

---

## 5. Explicit Simulation Assumptions & Scope Boundaries

### 5.1 What is Real vs. Synthetic
* **Real Components (Running Software & Network Stacks):**
  * Fully functioning Python software processes.
  * Real TCP/IP communication and standard Modbus TCP protocol packets (Function Code 03, 06, 16).
  * Real automated attacker scripts crafting network payloads.
  * Real inline command proxying, packet parsing, and command clamping.
  * Real mathematical physics equations evaluated in real time.
* **Synthetic Components (Process Models):**
  * The physical contact tank, raw water flow dynamics, disinfectant dissolution, and water quality telemetry are calculated numerically via a Continuous Stirred Tank Reactor (CSTR) differential equation.
  * Sensors and municipal water demand fluctuations are synthetically generated.

### 5.2 Model Assumptions
* Single Continuous Stirred Tank Reactor (CSTR) model.
* Perfectly mixed fluid volume (uniform concentration throughout the tank).
* Negligible pipe transport delay between injection nozzle and contact chamber.
* First-order chemical decay kinetics (disinfectant residual decay).
* Single chemical species (chlorine / sodium hypochlorite).
* Parameter values are synthetic engineering constants chosen for prototype stability.

### 5.3 Safety Claims & Scope Boundaries
To maintain rigorous engineering credibility before technical evaluators:
* **No Claim of Invention of Process Invariants:** We do not claim to have invented the concept of physics-based process invariants. Our contribution is the specific inline actuation-path architecture, deterministic clamping, and cumulative physical mass-deviation tracking.
* **No Universal Safety Claim:** We do not claim this prototype guarantees universal water treatment safety or is ready for production municipal deployment without certification.
* **No Claim of Zero False Positives:** Under violent unmodeled hydraulic transients (e.g. water hammer or pipe burst outside sensor range), physical model discrepancies could trigger clamping.
* **No Claim of Solving All Slow-Ramp Attacks:** The cumulative dose-deviation tracker detects cumulative drift *within the configured sliding window and mass budget*. Adversaries dosing below the budget threshold over infinite timescales are outside the sliding window horizon.
* **No AI/ML Hallucination:** AquaPhy uses zero machine learning or artificial neural networks. Every decision is mathematically deterministic, closed-form, and auditable.
* **Network Topology & Scope Limitation:** The prototype assumes the protected PLC is reachable only through the AquaPhy proxy on the demonstrated local architecture. A network attacker with direct access to the PLC endpoint could bypass the proxy; production deployment would require network segmentation and PLC access controls.
