# D-66 batch error precedence

**Question.** Exact batch precedence and what counts as an item error. (open point 5)

**What the specification says.** "Error precedence is: item errors in input order, settlement completeness, resulting current available funds, then historical total and available funds at every effective/event boundary."

**Choice.** Before items: 401 → 403 (not an operator; no body needed, D-01) → 400 body → 400/422 key → replay/reuse → batch shape 422 validation_failed (corrections missing / not an array / 0 or >32 entries / an entry not an object / duplicate payment_id).
1. Item errors, scanning items in input order; the first erroneous item decides; within one item: 422 validation_failed (fields as single corrections, incl. effective_at > now) → 404 not_found (unknown payment) → 422 linked_payment_immutable (capture or refund; members are allowed here) → 409 stale_revision → 422 refund_exceeds_payment. No per-item 403 (the operator may correct any payment).
2. Settlement checks, per settlement in order of its first member's appearance: 422 incomplete_settlement (not every member present), then 422 validation_failed (members' effective instants differ, compared by instant).
3. 409 insufficient_funds: after applying every item's difference, some wallet's current available < 0.
4. 409 historical_overdraft: some affected wallet's total or available < 0 at any boundary ≤ now with all new revisions (D-53 over the union of affected users).
Any failure claims no key and changes nothing.

**Effect on acceptance tests.** A precedence matrix tests each adjacent pair and 'first erroneous item wins'.
