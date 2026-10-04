# D-53 historical overdraft algorithm

**Question.** Which users, boundaries and fields historical_overdraft checks.

**What the specification says.** "if any user's corrected balance is negative at any effective-time boundary, return 409 historical_overdraft. Balances at a boundary include the combined effect of all movements at that instant." "if it makes either total or available negative at any past effective/event boundary, under the latest known revisions."

**Choice.** After the current-available check passes, build the corrected history for both parties of the payment (no other wallet changes): selected revisions = latest of every payment with the new revision included (K = +∞), plus every hold event known now. Boundaries = every distinct instant ≤ N among selected effective_at values and hold event times (creation, capture, void, expires_at ≤ N) touching that user, plus −∞ (the opening). At each boundary apply all changes at that instant together, then require total ≥ 0 and available = total − held ≥ 0. Any violation → 409 historical_overdraft with no state change. Future boundaries (expiries after N) only release holds and are not checked.

**Effect on acceptance tests.** Tests: overdraft via an earlier receiver spend; via a hold active at the effective time; same-instant combination prevents false positives.
