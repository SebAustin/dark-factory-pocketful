# D-47 revision shapes and revisions endpoint

**Question.** Revision 1 for every payment kind; item shape; what /revisions and receipts return; how effective_at is rendered. (open question 5, 6)

**What the specification says.** "Revision 1 has amount as originally paid and effective_at = recorded_at = created_at." "returns {\"revisions\": [...]} in revision order, including revision 1 (reason: \"\")". "The original payment and every original idempotent response remain unchanged."

**Choice.** Revision item = correction response shape: {payment_id, revision, amount, effective_at, recorded_at, reason}. Revision 1 for every kind (direct, request pay, settlement member, capture, seeded, imported): amount = original amount, effective_at = recorded_at = the payment's created_at string, reason "". Corrections: effective_at rendered exactly as supplied (string preserved), recorded_at server-assigned (D-41).
GET /payments/{id}/revisions: sender or receiver only; third party (incl. operators) → 404; unknown → 404; no token → 401; ascending revision. 
Payment objects everywhere outside statements (POST responses, replays, /activity, settlement and capture receipts) are the original payment: original amount and stage-2 key set, no revision fields. In statements, `payment` is the same object with `amount` replaced by the selected amount.

**Effect on acceptance tests.** Tests: revision 1 per kind; activity amount unchanged after corrections; statement payment.amount selected.
