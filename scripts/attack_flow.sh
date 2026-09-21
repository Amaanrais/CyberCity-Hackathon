#!/usr/bin/env bash
# Variant 4: Flow Sensor Falsification Attack
# Attacker leaves chemical sensors untouched, but falsifies the flow sensor reading to 15 L/s (vs 50 L/s nominal).
# The controller attempts to compensate mass balance and commands a massive concentration per litre.
# Caught because the interlock checks resulting ppm, not raw pump commands.
set -e
PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

echo ">>> [ATTACK 4] INJECTING FLOW SENSOR FALSIFICATION (Flow reported = 15 L/s)..."
curl -s -X POST "http://${HOST}:${PORT}/attack/flow_falsification" | python3 -m json.tool || curl -s -X POST "http://${HOST}:${PORT}/attack/flow_falsification"
echo ""
echo "Attack injected. Observe SCADA dashboard:"
echo " - Both Primary and Verification sensors read nominal 100 ppm"
echo " - Controller scales requested dose to 333 ppm (50 L/s / 15 L/s * 100 ppm)"
echo " - Tripped by: HARD_BOUND_EXCEEDED on resulting concentration"
