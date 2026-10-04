# D-44 seeded created at

**Question.** Equal seeded timestamps, seeded created_at equal to reset time, which clock judges 'future', and order against API payments. (open question 3)

**What the specification says.** "Seeded payments may supply created_at; omission uses reset time, before subsequent API-created payments. A seeded created_at in the future gives 422 validation_failed". "Entries are ordered by created_at ascending, then payment id ascending for ties."

**Choice.** Reset takes one reset instant R from the monotonic clock before validating. A supplied created_at is future iff its instant > R (→ 422, nothing changes); equal to R is accepted. Omitted created_at = R. Every later server-assigned instant is > R (monotonic), so API payments always follow seeded ones. Seeded payments with equal created_at (incl. several omitted → all R) are ordered by payment id ascending, compared by Unicode code point (`p_10` < `p_9`); the same tie-break applies to settlement members sharing committed_at. Seeded created_at keeps its full precision and its original string form.
Seeded requests and authorizations follow the same future rule for their own created_at (D-51 for authorizations); seeded expires_at may be in the past or future (stage 2).

**Effect on acceptance tests.** Tests: future → 422 unchanged; R-equivalent accepted; seeded-without-created_at before an API payment made right after reset; ties by id.
