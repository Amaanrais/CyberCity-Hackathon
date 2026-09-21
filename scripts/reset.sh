#!/usr/bin/env bash
# Reset the SCADA simulation to nominal 100.0 ppm baseline
set -e
PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

echo ">>> Resetting SCADA Plant Simulation to Nominal Baseline..."
curl -s -X POST "http://${HOST}:${PORT}/reset" | python3 -m json.tool || curl -s -X POST "http://${HOST}:${PORT}/reset"
echo ""
echo "System restored: Baseline = 100.0 ppm, Flow = 50.0 L/s, Interlock = ON, New Run ID generated."
