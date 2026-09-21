# TEAM-SHEET

### Defend What Matters: CyberMACS Student Hackathon

**Project name:** AquaLock SIS
**Track:** A - Resilience Under Attack
**Team name:** PUREIT
**Team members:** Amaan Rais, Amar Kumar Mandal, Mahdi Mohammad Shibli, Quazi Fariha Tasnim,  S M Dedar Alam

---

## Problem

CyberCity's water treatment plant runs on a SCADA system where a compromised operator credential gives an attacker fully authorized remote access to chemical dosing controls. Because the command arrives through legitimate channels, standard IT defenses (firewalls, authentication, encryption) see nothing wrong, since the PLC just executes the setpoint it's given, with no awareness of the physical chemistry it's about to unleash. This isn't hypothetical: in February 2021, an attacker used this exact access pattern against a real plant in Oldsmar, Florida, spiking sodium hydroxide dosing from ~100 ppm to ~11,100 ppm before an operator caught it manually. Plants also can't simply shut down on any anomaly: a hard emergency stop drops citywide water pressure, disabling firefighting and risking contaminated backflow. The defense must hold the line on safety without sacrificing availability.

## Who We're Defending

**CyberCity's water treatment SCADA operator**, the person on shift when a compromised credential issues a malicious dosing command, who needs the plant to physically refuse an unsafe command even when the network, login, and SCADA server are all fully compromised.

## Solution

We built **AquaLock SIS**, an independent Safety Instrumented System (SIS) interlock modeled on the IEC 61511 / ISA-84 standard. It sits between the SCADA control loop and the physical dosing pump as its own separate layer, unreachable even if SCADA is fully compromised. Every dosing command must pass three gates: (1) a **hard concentration ceiling of 150 ppm** on the projected finished-water concentration, closing off both direct dosing attacks and flow-sensor spoofing; (2) a **slew-rate limiter** rejecting any dose change faster than 40 ppm/second; and (3) a **dual-channel sensor cross-check** requiring the verification sensor to agree with the primary within 15%, debounced across samples. If an attack persists past 5 consecutive blocked commands, a fail-safe decay policy smoothly steps dosing back to the 100 ppm baseline instead of shutting the plant down. A live control-room dashboard (FastAPI + real-time charts) shows the attacker's requested dose, the "Ghost Line," next to the actual dose reaching the water, with every block logged and attributed to the gate that caught it.

## Next Steps (Post-Hackathon)

- Replace simulated sensors with real Modbus/OPC-UA integration against an actual PLC test rig.
- Build the interlock's key switch as genuine air-gapped hardware, not a UI toggle.
- Pursue formal ISA-84 compliance review against a certified SIL-3 logic solver (e.g., Triconex).
- Extend dual-channel redundancy to other parameters, like chlorine and fluoride.

## AI Tool Disclosure

We designed the system ourselves: the SIS architecture, the three safety gates and thresholds, the fail-safe decay policy, and the CyberCity/Oldsmar threat framing. We used **Claude Code (Anthropic)** as a coding assistant to speed up boilerplate (FastAPI routes, test scaffolding, chart wiring) and help draft documentation, which we then reviewed and revised ourselves. Every safety-critical decision was specified, checked, and owned by the team.

**Repo:** https://github.com/devded/i1 · **Docs:** `README.md`, `SYSTEM_DESIGN_AND_PITCH.md`, `docs/SYSTEM_EXPLAINED.md`
