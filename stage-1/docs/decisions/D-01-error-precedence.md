# D-01 error precedence

**Question.** Which error wins when several apply to one request?

**What the specification says.** Spec orders only some pairs: key resolution after auth + JSON-object parse and before field validation/resource checks (§7); settlement entry errors in input order before insufficient funds (§11).

**Choice.** Fixed order for every endpoint:
1. 401 `unauthenticated` (auth needs no body)
2. 403 `forbidden` for role checks that need no body (settlements: non-operator)
3. 400 `malformed_request` — body not parseable, or not a JSON object
4. 400 `missing_idempotency_key`, then 422 key length (1..255)
5. claimed key: 200 replay / 409 `idempotency_key_reuse`
6. body fields: wrong JSON type → 400; then 422 `validation_failed` (missing/range/format/length) in field order; then 422 `self_payment`/`self_request`
7. 404 `not_found` (handles, request id)
8. 403 `forbidden` (not payer / not requester)
9. 409 `request_not_pending`
10. 409 `insufficient_funds`
For pay/decline/cancel the request lookup (404) precedes the role check (403), which precedes state (409).

**Effect on acceptance tests.** Acceptance tests assert strictly only the pairs the spec orders (§7 key-before-validation, §11 entry order, pay replay-not-409). Other combinations accept either code.

**Constraining text.** "an already claimed key is resolved before endpoint field validation or current-resource checks"; "Entry errors take precedence in input order, before insufficient funds."
