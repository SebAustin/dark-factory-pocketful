# D-46 correction validation and rules

**Question.** Field typing, error order, stale direction, delta 0, zero amount, which payments are correctable, effective_at relative to created_at. (open question 4)

**What the specification says.** "All fields are required. Revision is a positive integer; amount is an integer 0..1000000000 (zero reverses the entire payment); reason is a string of 1..200 characters; effective time is an RFC 3339 instant not later than now. Invalid input is 422 validation_failed." Linked payments: settlement members and captures only.

**Choice.** Typing: every field defect — missing, null, wrong JSON type (string for a number, number for a string, bool), out of range, non-integral, malformed instant — is 422 validation_failed (endpoint rule overrides stage 1's 400 for wrong types). Integral JSON numbers (1.0, 1e0) are accepted for expected_revision and amount (stage 1 §4). reason length counts code points; whitespace-only is allowed (it has ≥ 1 character). A body that is not a JSON object is 400 malformed_request.
effective_at ≤ N (read instant of the correction, inclusive) — it may be earlier than the payment's created_at, earlier than reset, or later than created_at; only the overdraft rule limits it.
Order: 401 → 400 body → 400 missing key → 422 key length → replay 200 / 409 reuse → 422 fields → 404 unknown payment → 403 caller is not the original sender (receiver and third parties alike) → 422 linked_payment_immutable → 409 stale_revision (expected ≠ current latest, lower or higher) → 409 insufficient_funds (current available of the debited party) → 409 historical_overdraft → 201.
Allowed: amount equal to the current amount (delta 0; a new revision that may only move the effective time); amount 0 (reversal; later corrections may raise it again); request-pay, seeded, imported and zero-amount payments. A correction never touches the request (stays paid, same payment_id), the split, or the settlement/authorization records.

**Effect on acceptance tests.** Tests cover each rule; precedence tested pairwise where the order is decided here.
