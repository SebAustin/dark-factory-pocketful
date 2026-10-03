---
name: screen-craft
description: Build product screens that are specific, responsive, accessible and truthful about server state, from a specification's screen requirements. Use when implementing or reviewing any user-facing page.
---

# Screen craft

## Contract first

From the ledger, list for each screen: route, every named element and attribute (use the
specification's names exactly; tests find elements by them), every action, and every
state: empty, loading, success, validation error, server error, conflict or stale data,
uncertain outcome, signed out.

## Visual system

Before any screen, write a small token sheet as CSS custom properties: a palette chosen for
this product with one accent used for meaning (primary action, positive versus negative
change, error), a type scale with real contrast between levels, a spacing scale with uneven rhythm,
two radii, one elevation. Pick one deliberate style direction and say it in a decision
record. Self host every asset: no remote fonts, scripts or stylesheets; the container has
no network at run time. Prefer a system font stack or a bundled font file.

Avoid the template look: centred hero with gradient, uniform card grids, grey on white
with a single accent everywhere. Use hierarchy: the number the user cares about is the
largest thing on the screen.

**Numbers are atomic.** A value never wraps, truncates or overflows: keep it on one line
(`white-space: nowrap`), use tabular figures, and scale its size to its container (for
example `font-size: clamp(...)` with a container-relative middle term) so the largest value
the specification allows still fits at the narrowest supported width. Test with that
largest value, not with a typical one.

## Truthful client behaviour

- Disable a submitting control and show progress until the server answers.
- Show success only after the server confirms it. Show the server's error message near the
  control that caused it.
- When a request times out or the connection drops, the outcome is **unknown**: say so,
  keep the input, and offer a safe retry that reuses the same idempotency or request key
  so a retry cannot double the effect.
- When the server reports a conflict or stale data, refresh from the server and tell the
  user what changed instead of overwriting it.

## Accessibility and responsiveness

Every control has a label; focus is visible; the whole flow works by keyboard; colour is
never the only signal; layouts hold from 360 px to 1440 px without horizontal scrolling.

## Evidence

Screenshot each state at every viewport the specification names (otherwise 390 px and
1280 px wide) with a headless browser, save under `reviews/stage<N>/shots/`, and confirm the
console is free of errors.
