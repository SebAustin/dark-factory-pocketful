# D-72 refund of on payment shapes

**Question.** refund_of on payment objects and stored receipts. (open point 11)

**What the specification says.** "Other payments have refund_of: null." "Original payments and receipts never change."

**Choice.** Every payment object rendered by stage 4 (POST /payments, request pay, capture, settlement members, refunds, /activity, statement entry payment) has 14 keys: the stage-3 13 + refund_of. Stored idempotent responses (incl. those created before the upgrade or imported) replay verbatim, so a receipt stored without refund_of replays without it (as D-34).

**Effect on acceptance tests.** Carried key-set tests updated (D-75).
