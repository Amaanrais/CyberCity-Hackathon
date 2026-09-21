# Live Demo Script — AquaLock SIS (rehearsal copy)

Use this to rehearse the 90-second demo block (Slide 6 of `docs/Presentation_README.md`). This is the "say this / do this" version. For full API reference and the 4-vector defense-in-depth walkthrough, see `docs/DEMO_ATTACK_API.md`.

Per hackathon rules, have a **backup screen recording** of this exact sequence ready in case the live demo fails.

---

## Before you go on stage

- [ ] Server running: `python run.py` (or already running, confirm `http://localhost:8000/` loads)
- [ ] Dashboard open full-screen in browser, tab already focused
- [ ] Terminal open next to it with commands below ready to paste (or `scripts/*.sh` ready to run)
- [ ] Do one full silent dry run in the last hour before presenting
- [ ] Know who is typing (driver) and who is talking (narrator), don't do both

---

## Reading the dashboard — three charts

Know these cold before you go on. Left-to-right on the dashboard:

| Chart | Lines shown | What it's for | What to say while pointing |
|---|---|---|---|
| **Finished Water pH** | Single line: Finished Water pH, with reference lines at Safe Ceiling (8.5) and Hazard Threshold (10.0) | The actual human-facing consequence, is the water safe to drink right now | "This is the line that matters, everything else is mechanism. Safe below 8.5, caustic above 10." |
| **Dual Sensor Channels** | Primary Sensor (solid, the attack surface) vs Independent Verification Channel (dashed) | Shows the two independent NaOH readings Gate 3 cross-checks against each other | "The attacker can fake one of these. They can't easily fake both at once, that's the point of the second channel." |
| **Pump Actuator Dose** ("Ghost Line" chart) | Requested Dose / SCADA Command (dashed) vs Actual Actuator Dose (solid), with the SIS Hard Ceiling (150 ppm) marked | The core "adversary moment": what the attacker asked for vs what the pump actually did | "Watch the gap between these two lines open up, that gap is the interlock working." |

During Phase 2 (interlock off), the dashed and solid lines on the **Dose chart** will move together, since nothing is blocking the command. During Phase 3 (interlock on), that's the moment they split apart, call it out the instant you see it.

---

## Phase 1 — Baseline (~15s)

**Say:** "Here's the plant running normally. Interlock engaged, dose steady, pH safe."

**Do:**
```bash
bash scripts/reset.sh
```

**Point at:** dashboard shows ~100 ppm dose, pH ~7.60, status `NOMINAL OPERATION`.

---

## Phase 2 — Unprotected attack, the failure mode (~35s)

**Say:** "Now watch what happens with standard SCADA and no independent safety layer. We turn the interlock off and fire the exact attack from Oldsmar, Florida in 2021."

**Do:**
```bash
curl -s -X POST http://127.0.0.1:8000/interlock -H "Content-Type: application/json" -d '{"enabled": false}'
bash scripts/attack_oldsmar.sh
```

**Point at:** the actual-dose line ramping to 11,100 ppm, pH climbing out of the safe band into the red zone over ~15–20 seconds.

**Say (as it climbs):** "That's a valid, authenticated SCADA command. Nothing in standard IT security flags this. This is drinking water turning caustic."

---

## Phase 3 — Protected attack, the "Ghost Line" (~40s)

**Say:** "Same attack, interlock back on."

**Do:**
```bash
bash scripts/reset.sh
curl -s -X POST http://127.0.0.1:8000/interlock -H "Content-Type: application/json" -d '{"enabled": true}'
bash scripts/attack_oldsmar.sh
```

**Point at:**
- The dashed red line (requested dose) rocketing to 11,100 ppm, this is the **Ghost Line**, what the attacker asked for.
- The solid actual-dose line staying locked near the safe baseline.
- pH holding around 7.60.
- The audit log entry showing which gate blocked it.

**Say:** "The attacker's command never reaches the pump. Every block is logged with the exact gate that caught it."

**Close:** "That's the demo. The plant stays running, the water stays safe, even with the SCADA server fully compromised."

---

## If something breaks live

- Dashboard frozen / server crashed: switch straight to the backup recording, say "we'll show the recorded run" and keep narrating over it exactly as above.
- Attack doesn't visibly trip: check `/state` in the terminal (`curl -s http://127.0.0.1:8000/state | python3 -m json.tool`) and read out `last_decision` directly to the judges instead of relying on the chart.
- Running low on time: skip straight to Phase 3 (protected attack). The unprotected failure mode is nice-to-have, the protected defense is the point.
