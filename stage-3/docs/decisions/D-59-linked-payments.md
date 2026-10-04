# D-59 linked payments

**Question.** Which payments are linked and where that check sits.

**What the specification says.** "Single-payment corrections reject settlement members with 422 linked_payment_immutable." "a correction of a capture gives 422 linked_payment_immutable."

**Choice.** Linked = payment with non-null settlement_id or authorization_id (incl. imported ones). The check runs after 403 (only the sender reaches it) and before stale_revision. Linked payments still have revision 1 and appear in /revisions and statements.

**Effect on acceptance tests.** Tests: member and capture corrections by their sender with a valid body → 422 linked.
