# D-29 ttl validation

**Question.** Which `authorization_ttl_seconds` values are valid?

**What the specification says.** "If supplied, it must be a positive integer number of seconds."

**Choice.** Valid: JSON numbers with an integral value ≥ 1 (600, 600.0, 6e2, consistent with stage 1 §4 numbers). Invalid → reset 422 changing nothing: 0, negatives, fractions, strings, booleans, null.

**Effect on acceptance tests.** Tests: 0, -1, 1.5, "600", true, null → 422.
