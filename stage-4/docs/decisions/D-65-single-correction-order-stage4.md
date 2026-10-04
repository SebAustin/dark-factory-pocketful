# D-65 single correction order stage4

**Question.** Single-correction precedence with the new rules. (open point 4)

**What the specification says.** "Captures and refund payments cannot themselves be corrected: 422 linked_payment_immutable. A correction cannot reduce a payment below its already-refunded amount: 422 refund_exceeds_payment. Correction debits are checked against available funds."

**Choice.** Stage 3 order (D-46) extended: 401 → 400 → key → replay/reuse → 422 fields → 404 → 403 (not the original sender) → 422 linked_payment_immutable (settlement member, capture, refund) → 409 stale_revision → 422 refund_exceeds_payment (new amount < refunded total) → 409 insufficient_funds (debited party's current available) → 409 historical_overdraft. Stale comes before refund_exceeds: a stale request is answered without judging its value.

**Effect on acceptance tests.** Tests: stale beats refund_exceeds; refund_exceeds beats insufficient.
