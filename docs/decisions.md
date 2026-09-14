# AquaPhy — Architecture & Design Decisions Log

**Project:** AquaPhy — Inline Physical Safety Interlock for Legacy Water Treatment  
**Track:** Track A — Resilience Under Attack  
**Version:** 1.0 (Hackathon Architecture Specification)

---

## Decision 1: Active Inline Proxy Interlock vs. Passive Out-of-Band IDS

* **Status:** Accepted
* **Context:** Legacy water treatment facilities rely on legacy PLCs communicating over unauthenticated Modbus TCP. Prior defensive approaches typically deploy passive Network Intrusion Detection Systems (NIDS) tapping SPAN/mirror ports.
* **Decision:** Place AquaPhy directly in the actuation path as an active bump-in-the-wire Modbus TCP proxy intercepting commands between SCADA and the PLC.
* **Rationale:** In chemical dosing, water treatment reactions are irreversible. Once excessive sodium hypochlorite is injected into the contact basin, passive alerts arrive too late. An inline interlock deterministically validates or clamps packets *before* the PLC actuator register is modified.
* **Consequences:** Introduces proxy network processing overhead (aimed for low-latency operational inline evaluation). Requires a deterministic failure-handling policy if the proxy crashes or loses connectivity.

---

## Decision 2: Dual-Horizon Defense vs. Single Threshold or Slew-Rate Limiter

* **Status:** Accepted
* **Context:** Adversaries can attack water dosing via two contrasting profiles: abrupt setpoint spikes (acute poisoning) or low-and-slow creeping ramps (stealthy cumulative drift).
* **Decision:** Implement two complementary, physics-driven defense horizons:
  1. *Instantaneous Safety Envelope:* Closed-form single-step prediction ($C_{next} \le C_{max}$) derived from the CSTR differential mass balance.
  2. *Cumulative Dose-Deviation Tracker:* Sliding-window excess chemical mass accumulator ($M_{excess} \le M_{budget}$).
* **Rationale:** A simple instantaneous bound fails against slow-ramp attacks that stay just below the threshold. Conversely, a simple slew-rate limiter allows an attacker to eventually reach a toxic setpoint as long as the rate of change is low. Dual horizons bound both instantaneous risk and integrated drift.
* **Consequences:** Requires tracking a sliding window of historical excess mass in memory, adding modest state tracking.

---

## Decision 3: Physics-Derived Nominal Baseline vs. Attacker-Controllable History

* **Status:** Accepted
* **Context:** Many anomaly detection systems compare incoming setpoints against an Exponentially Weighted Moving Average (EWMA) or the "last accepted command" to detect deviations.
* **Decision:** Deriving the nominal dosing baseline $\dot{m}_{nom}(Q)$ strictly from physical operating conditions ($Q$, $C_{in}$, $C_{target}$, $k_{decay}$, $V$), completely independent of past command history.
* **Rationale:** If the baseline is derived from past commands, an attacker who increases commands slowly will shift the baseline itself, poisoning the reference. Physical conservation of mass cannot be poisoned by network packets.
* **Consequences:** The interlock must have real-time access to process flow telemetry ($Q$) to compute the dynamic baseline.

---

## Decision 4: Deterministic Clamping vs. Binary Process Trip / Hard Shutdown

* **Status:** Accepted
* **Context:** When an unsafe command is detected, a safety system can either trip the process (shut down pumps and open breaker) or clamp the command to the safe boundary.
* **Decision:** AquaPhy deterministically clamps out-of-bounds commands to the physical safety boundary ($u_{safe} = u_{max}^{inst}$ or $u_{nom}$) while logging an alarm, allowing safe water treatment to continue.
* **Rationale:** In municipal utilities, false trips cause immediate service disruptions, water hammer damage, and water outages for entire communities. Clamping provides "graceful degradation" and resilience under attack, ensuring clean water production continues uninterrupted.
* **Consequences:** The attacker is constrained to non-hazardous operating regimes without succeeding in a Denial-of-Service shutdown.

---

## Decision 5: Physical Mass Units ($\text{mg}$) vs. Percentage-Seconds

* **Status:** Accepted
* **Context:** Cumulative deviation can be tracked as dimensionless control errors (e.g. integral of error percentage over time, $\% \cdot \text{s}$) or as physical mass units ($\text{mg}$).
* **Decision:** Track cumulative excess chemical addition strictly in milligrams ($\text{mg}$) of active chemical:
  $$M_{excess} = \int \max\left(0, \dot{m}_{req} - \dot{m}_{nom}\right) dt \quad [\text{mg}]$$
* **Rationale:** Dimensionless percentage-seconds lack physical meaning when flow varies. Calculating actual excess chemical mass ($\text{mg}$) ties directly to toxicological exposure and chemical storage consumption, providing interpretable and auditable metrics for plant supervisors.
* **Consequences:** Requires multiplying normalized pump commands by pump delivery constant $k_{pump}$ ($\text{mg/s}$).

---

## Decision 6: Dynamic Flow Coupling ($Q$-Dependent Limits) vs. Static Limits

* **Status:** Accepted
* **Context:** Fixed static pump limits (e.g. "pump command must never exceed 60%") fail when municipal demand surges or drops.
* **Decision:** Both the instantaneous ceiling $u_{max}^{inst}(Q, C)$ and nominal baseline $\dot{m}_{nom}(Q)$ are dynamic functions of raw water flow $Q(t)$.
* **Rationale:** When water demand rises (e.g. morning peak hours), higher volumetric flow flushes disinfectant out faster, legitimately requiring higher pump output to sustain disinfection. Static limits would cause false alarms during peak flow or fail to detect over-dosing during night-time low flow.
* **Consequences:** Process flow sensor data must be available to the interlock.

---

## Decision 7: Prototype Failsafe Behavior (Hold Last Safe Setpoint)

* **Status:** Accepted
* **Context:** If the interlock loses communication with the PLC or crashes, a default fail behavior must be executed.
* **Decision:** For this prototype, if communication is interrupted or an internal error occurs, AquaPhy halts processing new commands and holds the last known-safe setpoint.
* **Rationale:** Dropping dosing immediately to zero discharges unchlorinated pathogenic water to residents. Ramping to maximum causes chemical toxicity. Holding the last known-safe setpoint maintains near-steady state during short transient disruptions.
* **Consequences:** Clearly documented as prototype behavior. In production municipal plants, failure behavior is governed by multi-tier safety PLCs and hardwired interlocks.

---

## Decision 8: Zero AI / ML — Closed-Form Mathematical Determinism with Thread-Safe Concurrency

* **Status:** Accepted
* **Context:** Many modern cybersecurity tools incorporate machine learning (neural networks, clustering, autoencoders) for OT anomaly detection. Concurrently, multithreaded command streams and telemetry polling could introduce non-deterministic state corruption if synchronization is neglected.
* **Decision:** Explicitly reject all AI, deep learning, and statistical models in favor of closed-form physical equations, implemented with strict internal mutex synchronization covering all state read-modify-write transitions.
* **Rationale:** 
  1. *Explainability:* OT operators and regulators reject "black-box" models.
  2. *Determinism & Thread-Safety:* Closed-form ODEs cannot hallucinate or suffer from distribution shift. Internal mutex synchronization ensures identical mathematical evaluation and mass accounting regardless of thread interleaving between SCADA commands and telemetry polls.
  3. *Latency:* Mathematical evaluations execute in microseconds, ensuring real-time Modbus compatibility without holding locks across network I/O.
  4. *Auditability:* Every clamp decision can be mathematically proven and verified.
* **Consequences:** Eliminates AI buzzwords and race conditions, strengthening technical credibility before serious OT security evaluators while explicitly acknowledging prototype scope boundaries (no universal real-world safety claim).

---

## Decision 9: CSTR Simulation Scope & Explicit Non-Claims

* **Status:** Accepted
* **Context:** Hackathons risk overpromising and failing technical scrutiny if simulation assumptions are masked as real-world claims.
* **Decision:** Formally define the physical simulation as a synthetic CSTR (single tank, perfectly mixed, first-order decay, no transport lag) and explicitly state all limitations in documentation and presentations.
* **Rationale:** Acknowledging engineering trade-offs and explicit assumptions demonstrates maturity, technical depth, and integrity.
* **Consequences:** Prevents judges from poking holes in unstated assumptions.

---

## Decision 10: Architectural Mass Budget (500 mg) vs. Accelerated Demo Profile (75 mg)

* **Status:** Accepted
* **Context:** The baseline engineering architecture specifies a cumulative mass budget $M_{budget} = 500.0\text{ mg}$, corresponding to ~50 seconds of 10% sustained excess chemical addition at nominal flow ($Q = 10\text{ L/s}$). However, live hackathon evaluations require rapid, deterministic demonstrations within compact presentation timeframes.
* **Decision:** Preserve the 500 mg parameter as the official physical architecture baseline while providing an explicit, documented demo-only configuration ($M_{budget}^{demo} = 75.0\text{ mg}$) for the live demonstration script.
* **Rationale:** Preserves mathematical integrity and realistic utility engineering equations in documentation without forcing evaluators to sit through multi-minute idle periods during a live presentation.
* **Consequences:** Code, tests, and demo scripts explicitly declare when the accelerated demo budget is active vs the architectural baseline.

---

## Decision 11: Predictive Horizon ($H = 50\text{ s}$) vs. Simulation Timestep ($\Delta t = 0.1\text{ s}$)

* **Status:** Accepted
* **Context:** The instantaneous safety ceiling derivation uses a projection horizon to bound allowable dosing setpoints before effluent breaches $C_{max}$.
* **Decision:** Clearly distinguish the discrete forward-Euler integration timestep ($\Delta t = 0.1\text{ s}$) from the short-horizon predictive safety envelope horizon ($H = 50.0\text{ s}$, corresponding to the hydraulic residence time constant $\tau = V / (Q_{nom} + k_{decay} V)$).
* **Rationale:** A 0.1-second horizon would allow near-100% pump spikes since concentration changes negligibly over 100 milliseconds, failing to prevent acute poisoning. The 50-second predictive horizon matches the physical mixing dynamics of the contact tank, establishing a short-horizon predictive safety envelope that constrains acute spikes.
* **Consequences:** Eliminates confusion between numerical solver step size and physical predictive lookahead.

