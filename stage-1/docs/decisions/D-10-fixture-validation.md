# D-10 fixture validation

**Question.** Which fixture defects make reset fail, and is failure atomic?

**What the specification says.** Only negative balance → 422 is stated; minor_units is 0, 2 or 3.

**Choice.** Reset returns 422 `validation_failed` and changes nothing for: negative balance, minor_units not in {0,2,3}, missing/ill-typed required user fields, duplicate user ids/handles/emails, handle not matching the pattern, payment/request referencing unknown users, invalid status/visibility, unknown operator id. Unparseable body → 400. Currency/minor_units are not cross-checked; seeded passwords are not checked against the signup length rule. Optional fixture fields default: payment note "", visibility public; request note ""; settlement_operator_ids [].

**Effect on acceptance tests.** Tests assert only negative balance (spec) and minor_units=1 (accept 422).

**Constraining text.** §4 fixture bullets.
