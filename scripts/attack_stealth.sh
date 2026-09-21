#!/usr/bin/env bash
# Variant 2: Single-Channel Stealth Attack
# Falsifies primary sensor moderately (135 ppm). Bypasses hard-bound and rate-of-change,
# caught exclusively by cross-checking against the independent verification channel.
set -e
PORT="${1:-8000}"
HOST="${2:-127.0.0.1}"

echo ">>> [ATTACK 2] INJECTING SINGLE-CHANNEL STEALTH: Primary Sensor -> 135 ppm..."
curl -s -X POST "http://${HOST}:${PORT}/attack/single_channel_stealth" | python3 -m json.tool || curl -s -X POST "http://${HOST}:${PORT}/attack/single_channel_stealth"
echo ""
echo "Attack injected. Observe SCADA dashboard:"
echo " - Rate of change (+35 ppm/s <= 40 ppm/s) and Hard bound (135 ppm <= 150 ppm) pass"
echo " - Tripped by: SENSOR_DISAGREEMENT (Primary 135 ppm vs Verification ~100 ppm)"
echo " - Demonstrates why an independent second sensor channel is vital"
