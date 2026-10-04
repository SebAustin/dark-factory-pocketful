# D-62 refund validation and order

**Question.** Refund error order, incl. idempotency precedence. (open point 1)

**What the specification says.** "Only the original receiver may refund, else 403 forbidden; unknown payment is 404. The target may be a direct payment, request payment or capture, but never a refund. Invalid amount is 422 validation_failed. ... 422 refund_exceeds_payment. Refunds of refunds give 422 invalid_refund_target. ... fails 409 insufficient_funds".

**Choice.** Order (first failure answers), extending D-01: 401 → 400 body (unparseable / not an object) → 400 missing key → 422 key length → claimed key: 200 replay / 409 idempotency_key_reuse → 422 validation_failed (amount, D-73) → 404 not_found (unknown payment) → 403 forbidden (caller is not the target's receiver: its sender, third parties and operators alike) → 422 invalid_refund_target (target is itself a refund) → 422 refund_exceeds_payment (cumulative refunds + amount > current corrected amount, D-63) → 409 insufficient_funds (receiver's current available < amount) → 201. Any 4xx claims no key. Unknown body fields (note, visibility, …) are ignored; the refund copies the target's note and visibility.

**Effect on acceptance tests.** Pairwise precedence tests for every adjacent pair.
