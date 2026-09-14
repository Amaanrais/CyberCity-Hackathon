# CyberCity Hackathon Rules

## Context

This repository is for the IACyC 2026 CyberMACS
"Defend What Matters" hackathon.

We are building ONE demonstrable defensive capability
for a fictional CyberCity environment.

## Core principle

Prefer one excellent working capability over many
incomplete features.

Never expand scope without explicit approval.

## Hackathon constraints

- All targets must be synthetic, local, self-owned,
  or organizer-provided.
- Never scan, probe, attack, or capture traffic from
  real systems.
- Never use real personal data.
- Use synthetic datasets.
- Offensive demonstrations may only target our own
  local lab.
- The defensive purpose must always be clear.

## Engineering

- Prefer a simple architecture.
- Minimize dependencies.
- Write tests for core security logic.
- Keep demos deterministic.
- Never present fake results as real detection.
- Clearly label simulated components.
- Do not rewrite working code unnecessarily.

## Agent behavior

Before major implementation:

1. Inspect the relevant repository files.
2. Explain the proposed change.
3. Identify files to change.
4. Implement the smallest useful version.
5. Run tests.
6. Verify behavior.
7. Report what changed.

Never silently change architecture.

## Scope

If a feature does not directly improve:

- Idea & innovation
- Implementation/demo
- Presentation
- Impact/feasibility

recommend not building it.

## Demo

The final demo must visibly show:

THREAT
→ ATTACK
→ DETECTION
→ RESPONSE
→ RESULT

The adversary moment must be observable.

## Token efficiency

- Do not repeatedly reread the whole repository.
- Read only relevant files.
- Use docs/ as project memory.
- Keep decisions in docs/decisions.md.
- Prefer targeted edits.
- Avoid unnecessary explanations.
- Do not duplicate existing functionality.

## Security

Never execute offensive actions against systems
outside our own controlled environment.

Never expose secrets, API keys, credentials,
or personal information.
