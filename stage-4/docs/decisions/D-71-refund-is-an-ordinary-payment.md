# D-71 refund is an ordinary payment

**Question.** How a refund behaves outside its endpoint. (open point 2)

**What the specification says.** "A refund is a new payment in the opposite direction, with refund_of naming the target, request_id: null, authorization_id: null, and the original note/visibility."

**Choice.** The refund payment: from = target's receiver, to = target's sender, amount = refund amount, note and visibility copied from the target, request_id null, authorization_id null, settlement_id null, refund_of = target id, created_at = a D-41 tick. It is a payment for every other purpose: /activity (feed visibility rule), statements (entry with delta), as_of/known_at views, revisions (revision 1 at created_at, correction_batch_id null), export/import. It is immutable (single and batch corrections → 422 linked_payment_immutable) and cannot be refunded (422 invalid_refund_target). It never touches the request, authorization, hold or settlement records.

**Effect on acceptance tests.** Tests read refunds on every surface.
