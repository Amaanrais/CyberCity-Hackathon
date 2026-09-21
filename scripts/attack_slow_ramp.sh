#!/usr/bin/env bash
# Variant 3: Slow Ramp / Dual-Compromise Attack
# Sophisticated attacker compromises BOTH Primary and Verification channels,
# ramping both up at +35 ppm/s. Bypasses cross-check and rate-of-change.
# Caught only by the absolute physical hard ceiling (150 ppm).
set -e
PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

echo ">>> [ATTACK 3] INJECTING SLOW RAMP / DUAL COMPROMISE (+35 ppm/s on both channels)..."
curl -s -X POST "http://${HOST}:${PORT}/attack/slow_ramp" | python3 -m json.tool || curl -s -X POST "http://${HOST}:${PORT}/attack/slow_ramp"
echo ""
echo "Attack injected. Observe SCADA dashboard:"
echo " - Cross-check passes (Primary == Verification)"
echo " - Slew rate limit passes (+35 ppm/s <= 40 ppm/s limit)"
echo " - Tripped by: HARD_BOUND_EXCEEDED once projected concentration exceeds 150.0 ppm"
echo " - Proves the necessity of concentric defense-in-depth"
