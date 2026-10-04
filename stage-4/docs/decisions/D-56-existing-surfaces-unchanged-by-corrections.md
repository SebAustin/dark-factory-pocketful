# D-56 existing surfaces unchanged by corrections

**Question.** What corrections leave untouched.

**What the specification says.** "The original payment and every original idempotent response remain unchanged. GET /activity continues to display the original payment; correction records are not new feed payments."

**Choice.** /activity items, payment receipts and their replays, request objects (status paid, payment_id), split and settlement receipts, authorization objects (captured_amount, payment_ids) all keep their original values after any correction; only wallet balances, /me temporal reads, statements and /revisions reflect it.

**Effect on acceptance tests.** Tests compare these surfaces byte-for-value before and after corrections.
