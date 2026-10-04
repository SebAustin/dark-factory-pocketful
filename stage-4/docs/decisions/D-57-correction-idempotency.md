# D-57 correction idempotency

**Question.** Idempotency of the eighth write path.

**What the specification says.** "requires an idempotency key"; "Successful replay returns that original revision with 200 even after newer revisions. Different body with the same key is 409 idempotency_key_reuse."

**Choice.** Stage 1 §7 applies unchanged: key scoped per user + method + path (path includes the payment id); claimed key resolved before validation and resource checks; any 4xx (422, 403, 404, stale, insufficient, overdraft) claims nothing; concurrent identical requests → one 201, others 200 identical; replay returns the stored 201 body (original revision, even after newer revisions).

**Effect on acceptance tests.** Tests reuse the stage-2 idempotency harness for this path.
