# AquaPhy — Technical Architecture & Physical Safety Specification

**Project:** AquaPhy — Inline Physical Safety Interlock for Legacy Water Treatment  
**Track:** Track A — Resilience Under Attack  
**Version:** 1.0 (Hackathon Architecture Specification)

---

## 1. System Overview & Architecture Diagram

AquaPhy is an active inline physical interlock positioned as a bump-in-the-wire proxy between supervisory control systems (SCADA / HMI or an attacker) and a water-treatment Programmable Logic Controller (PLC).

```
+-------------------------------------------------------------+
|                      ATTACKER / SCADA                       |
|   - Issues Modbus TCP write commands (FC06/FC16)           |
|   - Target: Chemical dosing pump setpoint u_req in [0, 1]   |
+-------------------------------------------------------------+
                              |
                              | Modbus TCP (Port 5020)
                              v
+=============================================================+
|                      AQUAPHY INTERLOCK                      |
|                                                             |
|  +-------------------------------------------------------+  |
|  |             Modbus Proxy & Ingress Parser             |  |
|  +-------------------------------------------------------+  |
|                             |                               |
|                             v                               |
|  +-------------------------------------------------------+  |
|  |            Dual-Horizon Physics Evaluator             |  |
|  |                                                       |  |
|  |  [Horizon 1: Short-Horizon Predictive Safety Envelope]  |  |
|  |  - Reads flow Q, concentration C                      |  |
|  |  - Evaluates predictive safety horizon H = 50.0 s      |  |
|  |  - Derives u_max_inst via CSTR model                  |  |
|  |                                                       |  |
|  |  [Horizon 2: Cumulative Dose-Deviation Tracker]       |  |
|  |  - Computes physical nominal mass baseline m_dot_nom  |  |
|  |  - Integrates excess mass M_excess over window W      |  |
|  |  - Evaluates against mass budget M_budget             |  |
|  +-------------------------------------------------------+  |
|                             |                               |
|                             v                               |
|  +-------------------------------------------------------+  |
|  |         Enforcement & Clamping Engine (FC06)          |  |
|  |  - If valid: forwards u_req                           |  |
|  |  - If violated: clamps to u_safe                      |  |
|  |  - Failsafe: on error/timeout, holds last known-safe  |  |
|  +-------------------------------------------------------+  |
|                             |                               |
+=============================================================+
                              |
                              | Validated / Clamped Modbus TCP (Port 502)
                              v
+-------------------------------------------------------------+
|                        SYNTHETIC PLC                        |
|   - Modbus TCP Server (Holding & Input Registers)           |
|   - Actuation register: Chemical Dosing Pump Setpoint       |
|   - Sensor registers: Raw Water Flow Q, Chemical Conc. C    |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                   CSTR PROCESS SIMULATION                   |
|   - Disinfection contact tank (V = 1000 L, dt = 0.1 s)      |
|   - Mass balance ODE: dC/dt = (Q/V)(C_in-C) + (k_p*u/V) - kC|
|   - Generates process telemetry (Q, C)                      |
+-------------------------------------------------------------+
                              |
                              v Telemetry Loop
+-------------------------------------------------------------+
|                 OPERATOR CONSOLE / DASHBOARD                |
|   - Live telemetry: u_req, u_safe, Flow Q, Conc C,          |
|     u_max boundary, M_excess vs M_budget, Interlock State   |
+-------------------------------------------------------------+
```

---

## 2. Mathematical Models & Derivations

### 2.1 Continuous Stirred Tank Reactor (CSTR) Dynamic Model
Disinfection contact chambers in municipal water treatment follow Continuous Stirred Tank Reactor dynamics with first-order disinfectant consumption (decay):

$$\frac{dC}{dt} = \frac{Q}{V}(C_{in} - C) + \frac{k_{pump} \cdot u}{V} - k_{decay} \cdot C$$

#### Dimensional Verification of Equation Terms:
| Variable / Term | Physical Meaning | Base Units | Verification |
| :--- | :--- | :--- | :--- |
| $C$ | Effluent chemical concentration | $\text{mg/L}$ | Primary state |
| $t$ | Simulation time | $\text{s}$ | Time dimension |
| $\frac{dC}{dt}$ | Rate of concentration change | $\frac{\text{mg}}{\text{L}\cdot\text{s}}$ | Rate of change |
| $Q$ | Raw water volumetric flow rate | $\text{L/s}$ | Volumetric flux |
| $V$ | Contact tank liquid volume | $\text{L}$ | Physical capacity |
| $\frac{Q}{V}$ | Space velocity / turnover frequency | $\text{s}^{-1}$ | Hydraulic retention inverse |
| $C_{in}$ | Inflow chemical concentration | $\text{mg/L}$ | Untreated water baseline |
| $\frac{Q}{V}(C_{in} - C)$ | Dilution / convective mass exchange rate | $\frac{\text{mg}}{\text{L}\cdot\text{s}}$ | $[1/\text{s}] \times [\text{mg/L}] = \frac{\text{mg}}{\text{L}\cdot\text{s}}$ ✓ |
| $u$ | Normalized pump command setpoint | Dimensionless $[0, 1]$ | $0.0 = 0\%$, $1.0 = 100\%$ |
| $k_{pump}$ | Maximum chemical mass delivery rate | $\text{mg/s}$ | Pump capacity at $u = 1.0$ |
| $k_{pump} \cdot u$ | Instantaneous chemical mass dosing rate | $\text{mg/s}$ | Dosing flux |
| $\frac{k_{pump} \cdot u}{V}$ | Volumetric concentration injection rate | $\frac{\text{mg}}{\text{L}\cdot\text{s}}$ | $\frac{[\text{mg/s}]}{[\text{L}]} = \frac{\text{mg}}{\text{L}\cdot\text{s}}$ ✓ |
| $k_{decay}$ | First-order chemical decay rate constant | $\text{s}^{-1}$ | Chlorine reaction rate |
| $k_{decay} \cdot C$ | Chemical decay reaction rate | $\frac{\text{mg}}{\text{L}\cdot\text{s}}$ | $[1/\text{s}] \times [\text{mg/L}] = \frac{\text{mg}}{\text{L}\cdot\text{s}}$ ✓ |

All terms evaluate consistently to $\frac{\text{mg}}{\text{L}\cdot\text{s}}$.

---

### 2.2 Horizon 1: Short-Horizon Predictive Safety Envelope Derivation

To bound dosing commands before toxic effluent reaches the distribution network, the interlock projects chemical concentration over a **short-horizon predictive safety envelope** of duration $H = 50.0\text{ s}$ (matching the reactor's nominal hydraulic residence time constant $\tau = \frac{V}{Q_{nom} + k_{decay} V}$).

> [!NOTE]
> **Distinction Between Timing Parameters:**
> * $\Delta t = 0.1\text{ s}$: Numerical simulation integration timestep used by the discrete CSTR differential solver.
> * $H = 50.0\text{ s}$: Short-horizon predictive safety horizon used by the algebraic interlock envelope to project effluent concentration. Describing $H$ as an Euler numerical timestep is incorrect; it is a physical predictive lookahead.

The predicted concentration at the lookahead horizon $H$ is:

$$C_{pred} = C + H \left[ \frac{Q}{V}(C_{in} - C) + \frac{k_{pump} \cdot u}{V} - k_{decay} \cdot C \right]$$

The physical safety requirement dictates that under no circumstance may a dosing command cause projected concentration to breach the regulatory safety limit $C_{max}$:

$$C_{pred} \le C_{max}$$

#### Step-by-Step Algebraic Derivation of $u_{max}^{inst}$:
1. Expand the inequality:
   $$C + H \left[ \frac{Q}{V}(C_{in} - C) + \frac{k_{pump} \cdot u}{V} - k_{decay} \cdot C \right] \le C_{max}$$

2. Subtract $C$ from both sides:
   $$H \left[ \frac{Q}{V}(C_{in} - C) + \frac{k_{pump} \cdot u}{V} - k_{decay} \cdot C \right] \le C_{max} - C$$

3. Divide by $H$ ($H > 0$):
   $$\frac{Q}{V}(C_{in} - C) + \frac{k_{pump} \cdot u}{V} - k_{decay} \cdot C \le \frac{C_{max} - C}{H}$$

4. Isolate the pump injection term:
   $$\frac{k_{pump} \cdot u}{V} \le \frac{C_{max} - C}{H} - \frac{Q}{V}(C_{in} - C) + k_{decay} \cdot C$$

5. Multiply both sides by tank volume $V$ ($V > 0$):
   $$k_{pump} \cdot u \le \frac{V}{H}(C_{max} - C) - Q(C_{in} - C) + k_{decay} \cdot V \cdot C$$

6. Divide both sides by pump capacity $k_{pump}$ ($k_{pump} > 0$):
   $$u \le \frac{1}{k_{pump}} \left[ \frac{V}{H}(C_{max} - C) - Q(C_{in} - C) + k_{decay} \cdot V \cdot C \right]$$

#### Dimensional Verification of Derived $u_{max}^{inst}$:
* $\frac{V}{H}(C_{max} - C)$: $\left[\frac{\text{L}}{\text{s}}\right] \times \left[\frac{\text{mg}}{\text{L}}\right] = \left[\frac{\text{mg}}{\text{s}}\right]$
* $Q(C_{in} - C)$: $\left[\frac{\text{L}}{\text{s}}\right] \times \left[\frac{\text{mg}}{\text{L}}\right] = \left[\frac{\text{mg}}{\text{s}}\right]$
* $k_{decay} \cdot V \cdot C$: $\left[\frac{1}{\text{s}}\right] \times [\text{L}] \times \left[\frac{\text{mg}}{\text{L}}\right] = \left[\frac{\text{mg}}{\text{s}}\right]$
* Bracketed sum dimension: $\left[\frac{\text{mg}}{\text{s}}\right]$ (mass flux rate)
* Multiplier $\frac{1}{k_{pump}}$ dimension: $\left[\frac{\text{s}}{\text{mg}}\right]$
* Resulting dimension: $\left[\frac{\text{s}}{\text{mg}}\right] \times \left[\frac{\text{mg}}{\text{s}}\right] = \mathbf{1} \quad \text{(Dimensionless scalar)}$ ✓

#### Physical Actuator Bounds & Clamping Rule:
Since the pump cannot run in reverse ($u \ge 0$) or exceed maximum mechanical capacity ($u \le 1.0$), the instantaneous ceiling is:

$$u_{max}^{inst}(Q, C) = \min\left(1.0, \; \max\left(0.0, \; \frac{1}{k_{pump}} \left[ \frac{V}{H}(C_{max} - C) - Q(C_{in} - C) + k_{decay} \cdot V \cdot C \right] \right)\right)$$

If an incoming requested command $u_{req} > u_{max}^{inst}$, AquaPhy deterministically clamps the transmitted command:

$$u_{safe}^{inst} = u_{max}^{inst}(Q, C)$$

---

### 2.3 Horizon 2: Cumulative Dose-Deviation Check

#### Rationale & Independence from Attacker History:
Comparing commands against the "last accepted command" or an Exponentially Weighted Moving Average (EWMA) of past commands is a fatal flaw in process security: an adversary executing a low-and-slow ramp can iteratively shift the reference baseline without triggering rate alarms.

**Core Rule:** The baseline MUST be derived strictly from physical process state and invariant operating requirements, completely independent of attacker-controlled command history.

#### 1. Physics-Derived Nominal Dosing Baseline ($\dot{m}_{nom}$):
In standard municipal operation, the plant aims to maintain target concentration $C_{target}$. At steady-state ($\frac{dC}{dt} = 0$, $C = C_{target}$):

$$0 = \frac{Q}{V}(C_{in} - C_{target}) + \frac{\dot{m}_{nom}}{V} - k_{decay} \cdot C_{target}$$

Solving for nominal chemical mass dosing rate $\dot{m}_{nom}$ in milligrams per second ($\text{mg/s}$):

$$\dot{m}_{nom}(Q) = Q(C_{target} - C_{in}) + k_{decay} \cdot V \cdot C_{target}$$

Corresponding nominal command setpoint:

$$u_{nom}(Q) = \frac{\dot{m}_{nom}(Q)}{k_{pump}} = \frac{Q(C_{target} - C_{in}) + k_{decay} \cdot V \cdot C_{target}}{k_{pump}}$$

#### 2. Flow Coupling:
The nominal requirement $\dot{m}_{nom}(Q)$ scales directly with raw water flow $Q$. If municipal water demand doubles, $Q$ increases, requiring proportionally more chemical mass to disinfect the larger volume. AquaPhy dynamically updates $\dot{m}_{nom}(Q)$ each cycle based on measured flow telemetry $Q(t)$, allowing legitimate demand surges to be serviced without triggering spurious clamping.

#### 3. Excess Chemical Mass Accumulation:
The requested chemical dosing mass rate at time $t$ is:

$$\dot{m}_{req}(t) = k_{pump} \cdot u_{req}(t) \quad [\text{mg/s}]$$

Excess mass injection rate relative to the physics-derived nominal baseline:

$$\Delta \dot{m}_{excess}(t) = \max\left(0.0, \; \dot{m}_{req}(t) - \dot{m}_{nom}(Q(t))\right) \quad [\text{mg/s}]$$

Over a configured sliding time window of duration $W$ (seconds), the cumulative excess chemical mass is:

$$M_{excess}(t) = \int_{t-W}^{t} \Delta \dot{m}_{excess}(\tau) \, d\tau \quad [\text{mg}]$$

In discrete simulation time with fixed step $\Delta t$ and window sample count $N_W = \lfloor W / \Delta t \rfloor$:

$$M_{excess}[k] = \sum_{j = k - N_W + 1}^{k} \max\left(0.0, \; \dot{m}_{req}[j] - \dot{m}_{nom}(Q[j])\right) \cdot \Delta t \quad [\text{mg}]$$

#### 4. Mass Budget & Enforcement Action:
AquaPhy configures an allowable excess mass budget $M_{budget}$ in milligrams ($\text{mg}$). 

* When $M_{excess}[k] \le M_{budget}$: The system is in `NORMAL` state.
* When $M_{excess}[k] > M_{budget}$: The cumulative drift budget is breached. The system enters `CLAMPED_CUMULATIVE` state.
* Enforcement Rule: Any subsequent command requesting mass addition above nominal is clamped to nominal:
  $$u_{safe} = \min\left(u_{req}, \; u_{nom}(Q)\right)$$
  This halts further excess mass accumulation while sustaining normal treatment flow.

#### Explicit Limitation:
> [!IMPORTANT]
> The cumulative dose-deviation tracker detects cumulative drift **within the configured sliding window $W$ and mass budget $M_{budget}$**. It does not solve all conceivable stealthy manipulation across infinite time horizons.

---

## 3. Physical Constants & Simulation Parameters

The synthetic CSTR prototype uses consistent physical constants representing a scaled municipal contact chamber:

| Parameter | Symbol | Nominal Value | Units | Physical Rationale |
| :--- | :--- | :--- | :--- | :--- |
| Tank Liquid Volume | $V$ | $1000.0$ | $\text{L}$ | Scaled municipal contact tank |
| Raw Inflow Water Flow | $Q$ | $10.0$ (varies $5.0 - 20.0$) | $\text{L/s}$ | Nominal 100-second hydraulic retention time |
| Inflow Concentration | $C_{in}$ | $0.0$ | $\text{mg/L}$ | Raw, unchlorinated surface source water |
| Target Concentration | $C_{target}$ | $2.0$ | $\text{mg/L}$ | Target residual disinfectant level |
| Max Safety Concentration | $C_{max}$ | $4.0$ | $\text{mg/L}$ | EPA Maximum Residual Disinfectant Level (MRDL) |
| Max Pump Delivery Rate | $k_{pump}$ | $100.0$ | $\text{mg/s}$ | Maximum chemical feed pump mass delivery |
| First-Order Decay Rate | $k_{decay}$ | $0.01$ | $\text{s}^{-1}$ | Chlorine residual reaction rate constant |
| Simulation Timestep | $\Delta t$ | $0.1$ | $\text{s}$ | Discrete simulation integration timestep |
| Predictive Safety Horizon | $H$ | $50.0$ | $\text{s}$ | Short-horizon predictive envelope ($H = \tau = 50.0\text{ s}$) |
| Cumulative Sliding Window | $W$ | $60.0$ | $\text{s}$ | 60-second sliding history window ($N_W = 600$ steps) |
| Cumulative Mass Budget (Architectural) | $M_{budget}$ | $500.0$ | $\text{mg}$ | Baseline architectural budget (~50s of 10% sustained excess) |
| Cumulative Mass Budget (Demo Profile) | $M_{budget}^{demo}$ | $75.0$ | $\text{mg}$ | Accelerated demo-only configuration for 15s live evaluation |

#### Working Example: Nominal Baseline at $Q = 10\text{ L/s}$:
$$\dot{m}_{nom} = 10.0 \cdot (2.0 - 0.0) + 0.01 \cdot 1000.0 \cdot 2.0 = 20.0 + 20.0 = 40.0\text{ mg/s}$$
$$u_{nom} = \frac{40.0\text{ mg/s}}{100.0\text{ mg/s}} = 0.40 \quad (40\% \text{ pump speed})$$

---

## 4. Failure Modes & Prototype Behavior

### 4.1 Communication Loss & Internal Errors
If AquaPhy encounters an unhandled exception, loses TCP connectivity to the Synthetic PLC, or fails to receive telemetry within a configured timeout (e.g., $1.0\text{ s}$):
* **Failsafe Action:** AquaPhy stops forwarding incoming dosing commands and transitions to `FAILSAFE_HOLD`.
* **Actuation State:** It holds the **last known-safe validated setpoint** (or transmits a configured safe nominal fallback command $u_{nom}$).
* **Rationale:** In municipal water disinfection, dropping dosing immediately to zero risks discharging unchlorinated pathogen-bearing water into the public distribution grid, while driving the pump to 100% risks chemical poisoning. Holding the last known-safe command provides a stable, conservative holding pattern.

> [!WARNING]
> **Prototype Behavior Clarification:** Holding the last known-safe setpoint is the selected behavior for this hackathon prototype under loss of communication. In a real municipal plant, fail-safe modes depend on plant-specific Hazard and Operability (HAZOP) studies, dual-redundant safety PLCs, and hardwired mechanical shutoffs.

---

## 5. Novelty Positioning & Prior Art Distinction

Academic research has explored process-aware anomaly detection and physical invariants (e.g., SWaT testbed, MiniCPS, Process-Aware IDS). AquaPhy differentiates itself through three specific contributions:

| Dimension | Prior Art / Conventional Research | AquaPhy Hackathon Contribution |
| :--- | :--- | :--- |
| **Enforcement Path** | Passive anomaly detection on mirrored network traffic (SPAN) | **Active inline bump-in-the-wire proxy** intercepting Modbus writes *before* PLC actuation |
| **Intervention Strategy** | Post-hoc alerting or total emergency shutdown (trip) | **Deterministic closed-form clamping**: allows operation up to the physical safety boundary without tripping the process |
| **Cumulative Tracking** | Rate-of-change thresholds or moving average compared to past attacker commands | **Physical cumulative mass-deviation budget ($M_{excess}$ in $\text{mg}$)** integrated against a physics-derived invariant baseline |

---

## 6. Real-Time Telemetry & Dashboard Specifications

The interactive operator dashboard displays continuous real-time state:

1. **Control Command Stream:**
   * Requested Command ($u_{req}$) [0 – 100%]
   * Safe Forwarded Command ($u_{safe}$) [0 – 100%]
2. **Physical Process Telemetry:**
   * Current Water Flow ($Q$) [$\text{L/s}$]
   * Tank Chemical Concentration ($C$) [$\text{mg/L}$] vs Target ($C_{target}$) and Limit ($C_{max}$)
3. **Safety Envelope Telemetry:**
   * Dynamic Instantaneous Ceiling ($u_{max}^{inst}$) [0 – 100%]
   * Nominal Demand Baseline ($u_{nom}$) [0 – 100%]
4. **Cumulative Defense Telemetry:**
   * Cumulative Excess Mass ($M_{excess}$) [$\text{mg}$]
   * Cumulative Mass Budget ($M_{budget}$) [$\text{mg}$]
5. **Defense Operational State:**
   * `NORMAL`: Transparent forwarding of safe commands.
   * `CLAMPED_INSTANTANEOUS`: Command exceeded single-step safety ceiling; clamped to $u_{max}^{inst}$.
   * `CLAMPED_CUMULATIVE`: 60-second excess mass budget exhausted; clamped to $u_{nom}$.
   * `FAILSAFE_HOLD`: Communication or hardware fault; holding safe setpoint.
