---
name: diagnose
description: Diagnosis loop for a failure that keeps coming back, a flaky result or a race. Use when the same rejection has returned twice or a check fails intermittently.
---

# Diagnose

Adapted from Matt Pocock's `diagnosing-bugs` skill (MIT).

## 1. Build a tight loop that goes red

Before forming any theory, write one command that drives the real failing path and asserts
the exact symptom: a request script against the running container, a failing test, or a
concurrent burst followed by an invariant check. Make it fast and deterministic; for races,
raise the reproduction rate (more parallel requests, more repetitions) until it fails
reliably. No red loop, no hypotheses.

## 2. Minimise

Remove inputs, steps and data one at a time, re-running after each cut, until every
remaining element is needed for the failure.

## 3. Hypothesise

Write three to five ranked hypotheses, each falsifiable: "if X is the cause, changing Y
makes the failure disappear". Test them one variable at a time. Tag any temporary logging
with a unique prefix so it can be removed with one search.

## 4. Hand over

Send the owner a packet: the red command, the minimal reproduction, the proven cause, the
requirement id it violates with its quote, and a suggested regression test at the right
seam. If no seam can reach the failure, say so; that is an architecture finding for the
lead.
