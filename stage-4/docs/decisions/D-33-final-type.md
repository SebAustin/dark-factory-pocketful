# D-33 final type

**Question.** Wrong JSON type for `final`.

**What the specification says.** "final is boolean, default true"; stage 1 §5: wrong JSON type → 400.

**Choice.** Non-boolean `final` (including null, 0, "false") → 400 malformed_request; omission → true.

**Effect on acceptance tests.** Tests accept 400 (strict) — 422 also accepted for null.
