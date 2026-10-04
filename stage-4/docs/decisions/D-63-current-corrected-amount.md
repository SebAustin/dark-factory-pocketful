# D-63 current corrected amount

**Question.** What is the 'current corrected amount', and how are cumulative refunds counted? (open point 2)

**What the specification says.** "Refunds cumulatively may not exceed the payment's current corrected amount".

**Choice.** Current corrected amount = the amount of the target's latest revision at the request's read instant (everything known; not as_of/known_at). Cumulative refunds = Σ amounts of all refund payments whose refund_of is the target (refunds are immutable). Check: cumulative + amount ≤ current corrected amount. A target corrected to 0 cannot be refunded (any amount ≥ 1 exceeds). If a later correction raises the amount, more can be refunded. Refunds do not change the target's revisions.

**Effect on acceptance tests.** Tests correct down/up and refund to the exact remainder.
