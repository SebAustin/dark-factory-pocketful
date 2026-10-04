# D-49 statement response shape

**Question.** Exact statement response and entry keys; window validation.

**What the specification says.** "Each entry retains payment, delta and balance_after, and adds the selected revision, effective_at and recorded_at." Every first response "additionally returns an opaque snapshot token".

**Choice.** Response: {opening_balance, entries: [{payment, delta, revision, effective_at, recorded_at, balance_after}], closing_balance, has_more, snapshot} plus `known_at` (echo) when supplied. `payment` = stage-2 payment object (13 keys) with amount = selected amount. A snapshot page has the same shape and returns the same token. has_more = more entries exist beyond offset+limit in the full (frozen) list.
Validation: limit/offset as GET /requests; from/to/known_at per D-42; from > to → 422; from = to → empty entries, opening = closing.

**Effect on acceptance tests.** Tests assert the exact key sets.
