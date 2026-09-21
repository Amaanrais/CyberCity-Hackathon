# AquaLock SIS — Spoken Script (5 minutes)

Word-for-word talk track for `docs/PUREIT_Presentation.pptx` (8 slides). Built from `docs/Presentation_README.md`. Read it, don't recite it — but every fact and number below is locked to the source docs.

One line to remember the whole pitch: **"SCADA said yes. Our box said no."**

---

## Slide 1 — Title (0:00–0:10)

> "In February 2021, an attacker turned a water plant's drinking water into caustic drain cleaner — using nothing but a valid login. We built the thing that should have stopped it. This is AquaLock SIS."

---

## Slide 2 — The threat (0:10–0:55)

> "Picture the operator on shift at CyberCity's water plant. A compromised credential sends one command: raise the sodium hydroxide dose. SCADA accepts it. The pump obeys blindly — it has no idea what the chemistry does next.
>
> This isn't hypothetical. In Oldsmar, Florida, 2021, that exact command spiked dosing from 100 parts per million to over 11,000. A human operator caught it in time. We're not betting on that happening twice.
>
> And you can't just slam an emergency stop either — that kills water pressure citywide, kills firefighting capacity, and risks backflow.
>
> So here's the question we're answering: how do you build a safety layer that holds even when the operator, the network, and SCADA itself are all compromised — without shutting the water off?"

---

## Slide 3 — An independent safety layer (0:55–1:30)

> "AquaLock SIS. An out-of-band safety instrumented system, sitting between SCADA and the physical dosing pump, modeled on IEC 61511 and ISA-84. Even a fully compromised SCADA server can't reach past it. Every command has to clear three independent gates before it ever touches the pump.
>
> To be upfront: this is a prototype interlock. Real hardware isolation and a physical key switch are future work — we're not claiming certification tonight."

---

## Slide 4 — Three safety gates (1:30–2:05)

> "Gate one: a 150 ppm ceiling — on the *projected finished-water concentration*, not the raw pump stroke, so spoofing the flow sensor doesn't get you around it.
>
> Gate two: a 40 ppm-per-second slew limit. Change the dose faster than that, and it's rejected outright.
>
> Gate three: a second, independent sensor has to agree with the first within 15%, checked across multiple samples — not just one noisy reading.
>
> These thresholds are our prototype numbers, not certified drinking-water limits. Real deployment needs plant-specific validation."

---

## Slide 5 — Response to a sustained attack (2:05–2:30)

> "What happens if the attack keeps coming? After five blocked commands in a row, the system doesn't just freeze — it decays the dose smoothly back to the 100 ppm baseline. The plant keeps running while it self-corrects."

---

## Slide 6 — Live demonstration (2:30–4:00)

*(Follow `docs/DEMO_ATTACK_API.md` — narrate lightly, let the demo breathe.)*

> "Let's see it. Interlock on, baseline — pH 7.6, dose 100 ppm, nominal.
>
> Now I turn the interlock off and fire the same Oldsmar attack. Watch the pump — it ramps straight to 11,100 ppm, pH climbs into the red. This is SCADA alone.
>
> Reset. Interlock back on. Same attack, fired again. Watch the dashboard: the dashed line is what the attacker *asked* for — it rockets up. The solid line is what the pump *actually did* — it doesn't move. pH stays at 7.6.
>
> Here's *how*. Every command from SCADA has to pass through our interlock before it ever reaches the pump. The attack spoofs the primary sensor to 11,100 ppm — that's the dashed 'Ghost Line.' The interlock takes that requested value, projects what it would actually do to the finished water — mass over flow — and checks it against the 150 ppm ceiling. 11,100 blows straight through it, so gate one trips instantly. The pump never receives the command; it just holds the last safe setpoint, 100 ppm. That's the fix: the interlock trusts the physics, not the sensor reading, and it sits in the one place — right before the pump — that a compromised SCADA server can't reach around.
>
> And it's logged either way: here's the audit entry — `decision: BLOCKED, reason: projected resulting concentration 11100.0 ppm > 150.0 ppm limit, gate_tripped: HARD_BOUND`. Every rejected command goes to a separate audit database SCADA can't touch, so there's a forensic trail even if the attacker owns the plant server."

---

## Slide 7 — Path to industrial validation (4:00–4:30)

> "To take this from prototype to plant: real Modbus and OPC-UA integration against an actual PLC rig. A genuine air-gapped key switch, not a UI toggle. A formal ISA-84 review against a certified SIL-3 logic solver, like Triconex. And the same dual-channel check extended to chlorine and fluoride."

---

## Slide 8 — Thank you (4:30–4:40)

> "That's AquaLock SIS. Code's on GitHub at devded/i1. Claude Code helped with boilerplate and docs — every safety-critical decision was ours. Happy to take questions."

---

## Backup Q&A

| Question | Answer |
|---|---|
| Why can't the hacker just call the API and turn the interlock off? | Real SIS hardware is air-gapped and key-switched on dedicated SIL-3 hardware. Our on-screen toggle stands in for that physical switch — it isn't a network-exposed control in a real deployment. |
| Why decay the dose instead of freezing it once an attack is caught? | Freezing at an elevated setpoint holds no safety margin forever. Decaying back to the 100 ppm baseline actively restores it. |
| Why check concentration instead of raw pump stroke? | An attacker can spoof the flow meter instead of the dose itself. Checking the projected resulting concentration — mass over flow — catches that; a raw stroke check doesn't. |

---

**Memory hooks for delivery:** Oldsmar → 100 to 11,100 ppm. Three gates → ceiling, slew, cross-check. Five strikes → decay to baseline. One sentence → "SCADA said yes. Our box said no."
