# D-64 settlement members refund and correction paths

**Question.** Refunds of settlement members; single vs batch correction of members; refund floor in a later batch. (open points 3, 8)

**What the specification says.** "A settlement payment may be refunded under the existing refund rules, but refunds never change settlement membership." "Ordinary single-payment corrections remain available for nonmembers." "Correcting any settlement member requires including every member of that settlement".

**Choice.** A member's receiver may refund it (ordinary rules); the refund is a new non-member payment (settlement_id null). The single correction path keeps rejecting members with 422 linked_payment_immutable (stage 3 R3-SET.3); only an operator's batch may correct members, and then all members of that settlement must be present. A batch item that would set a member (or any payment) below its refunded total is 422 refund_exceeds_payment (an item error, D-66).

**Effect on acceptance tests.** Tests: member refund keeps membership; single correction of a member stays 422; refunded member in a reversing batch → 422 refund_exceeds_payment.
