# D-32 authorization shape

**Question.** Exact key set of an authorization object.

**What the specification says.** 201 example + 'Every authorization response adds remaining_amount' + 'payment_ids lists every capture in order'.

**Choice.** Keys: authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount, remaining_amount, currency, note, visibility, status, expires_at, payment_id, payment_ids, created_at. `payment_ids` is always present ([] before any capture). `status` is the effective status (clock expiry applied).

**Effect on acceptance tests.** Tests assert this exact set.
