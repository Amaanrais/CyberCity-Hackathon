#!/usr/bin/env bash
# Variant 1: Oldsmar Spike Attack
# Falsifies the primary dosing sensor reading to 11,100 ppm (mirroring the Oldsmar, Florida SCADA attack).
set -e
PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

echo ">>> [ATTACK 1] INJECTING OLDSMAR SPIKE: Primary Sensor -> 11,100 ppm..."
curl -s -X POST "http://${HOST}:${PORT}/attack/oldsmar_spike" | python3 -m json.tool || curl -s -X POST "http://${HOST}:${PORT}/attack/oldsmar_spike"
echo ""
echo "Attack injected. Observe SCADA dashboard:"
echo " - If Interlock is OFF: Actual dose spikes to 11,100 ppm, pH climbs into dangerous band (>10.0)"
echo " - If Interlock is ON:  Requested dose spikes (dashed red), Actual dose locked at safe ceiling (solid cyan)"
