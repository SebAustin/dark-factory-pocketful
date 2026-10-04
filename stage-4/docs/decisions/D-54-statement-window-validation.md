# D-54 statement window validation

**Question.** from/to edge cases.

**What the specification says.** "half-open window [from, to)"; invalid instants 422.

**Choice.** from > to (by instant) → 422 validation_failed. from = to → valid, entries [], opening = closing. Either may be in the future or before every payment.

**Effect on acceptance tests.** Tests: R3-ST.12.
