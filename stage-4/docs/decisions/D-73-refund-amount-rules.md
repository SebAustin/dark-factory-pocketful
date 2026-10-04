# D-73 refund amount rules

**Question.** Refund amount validation.

**What the specification says.** "Invalid amount is 422 validation_failed."

**Choice.** amount required; integral JSON number 1..1000000000 (1e3 and 1000.0 accepted, stage 1 §4); 0, negatives, fractions, > 1e9, strings, booleans, null, missing → 422 validation_failed. The cap against the target (refund_exceeds_payment) is a separate later check.

**Effect on acceptance tests.** Parametrised amount tests.
