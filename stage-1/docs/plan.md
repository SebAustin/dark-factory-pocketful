# Stage 1 implementation plan — Pocketful payments and settlements

Packet: S1.P. Source: `runlog/stage1-spec.md` (§1–§11). Author: Builder.

## 0. Shape in one paragraph

One Python 3.12 process, standard library only. `http.server.ThreadingHTTPServer`
(`daemon_threads = True`, `request_queue_size = 1024`, HTTP/1.1 with `Content-Length` on every
response) dispatches through one routing table. All service state is one in-memory object made of
plain JSON-serialisable dicts and lists, guarded by **one** `threading.Lock`. Every request that
reads or writes state runs its whole state section — idempotency lookup, validation against state,
balance checks, the effect, and storing the idempotent response — while holding that lock. The
only work done outside the lock is socket I/O, JSON parsing, and password hashing (scrypt), which is
slow and must not serialise the service. Image: `python:3.12-alpine`, no runtime dependencies.

## 1. Module layout and interfaces

All paths are under `stage-1/`.

| File | Responsibility | Interface (what other modules use) |
|---|---|---|
| `app/server.py` | Entry point. Reads `PORT` (default 8080), binds `0.0.0.0`, builds `ThreadingHTTPServer`, one `Handler` class for all methods. Wraps every dispatch in a catch-all that turns an unexpected exception into a 500 envelope (never a dropped connection). | `main()` |
| `app/http_util.py` | Request context and response writing: read body by `Content-Length`, parse JSON (`parse_float=Decimal`, `parse_constant` rejects `NaN`/`Infinity`), parse query string, extract bearer token and `Idempotency-Key`, write JSON with `application/json; charset=utf-8`; 204 with no body. | `Ctx` (method, path, path_params, query, headers, raw_body, `json_object()`), `send_json(handler, status, obj)` |
| `app/routes.py` | Routing table: list of `(method, regex, handler, flags)`; flags = `auth`, `idempotent`, `operator`. Unknown path → 404 `not_found`; known path, wrong method → 405 `method_not_allowed` (envelope). Runs the pipeline in §5 below. | `route(method, pattern, auth=True, idempotent=False, operator=False)` decorator; `dispatch(ctx) -> (status, body)` |
| `app/errors.py` | `ApiError(status, code, message)` and helpers `malformed()`, `validation()`, `not_found()`, `forbidden()`, `conflict(code)`; `envelope(err)`. | `ApiError` |
| `app/validation.py` | Field parsers, one rule per function, shared by every endpoint (§6 below). | `amount(v)`, `note(v)`, `visibility(v)`, `req_str(body, name)`, `handle_value(v)`, `query_int(q, name, default, lo, hi)`, `query_enum(q, name, allowed)`, `canonical(value)` |
| `app/store.py` | The state object, the lock, id generation, the clock, and the **only** functions that change balances. View builders for payment/request JSON. Fixture loader for reset. | `STORE` (has `.lock`, `.state`), `now_ts()`, `new_id(kind)`, `user_by_handle(h)`, `apply_transfer(...)`, `apply_batch(...)`, `payment_view(p)`, `request_view(r)`, `load_fixture(obj) -> State`, `replace_state(state)` |
| `app/auth.py` | Signup, login, `GET /me`, password hashing, token issue/lookup, handle derivation. | handlers; `hash_password(pw) -> str`, `verify_password(pw, stored) -> bool`, `derive_handle(email)`, `user_for_token(tok)` |
| `app/idempotency.py` | Per-user key records and the replay decision; called by `routes.dispatch` inside the lock for routes flagged `idempotent`. | `resolve(user_id, method, path, key, canon_body) -> None | (status, body)`, `record(user_id, method, path, key, canon_body, body)` |
| `app/payments.py` | `POST /payments`, `GET /activity`, feed rule. | handlers; `visible_to(payment, user_id)` |
| `app/requests_.py` | `POST /requests`, `POST /requests/{id}/pay|decline|cancel`, `GET /requests`. | handlers; `create_request(requester, payer, amount, note, ts) -> request` (used by splits) |
| `app/splits.py` | `POST /splits`, §9 share rule. | handler; `shares(amount, n) -> list[int]` |
| `app/settlements.py` | `POST /settlements`, §11. | handler |
| `app/transfer_io.py` | `GET /_test/export`, `POST /_test/import`, state validation for import. | handlers |
| `app/testctl.py` | `GET /health`, `POST /_test/reset`. | handlers |
| `tests/` | `unittest` suites; `tests/harness.py` starts the server in-process on an ephemeral port and offers `call(method, path, body, token, key)`. | — |
| `Dockerfile`, `RUN.md` | Build and single-command start. | — |

### State shape (store.py — every module reads/writes only through these keys)

```
state = {
  "currency": "EUR", "minor_units": 2,
  "users":    { user_id: {id, email, email_lc, password_hash, display_name, handle, balance} },
  "handles":  { handle: user_id },          # unique index
  "emails":   { email_lc: user_id },        # unique index
  "tokens":   { token: user_id },
  "operators":[ user_id, ... ],
  "payments": { payment_id: {id, from, to, amount, note, visibility, request_id, settlement_id, created_at, seq} },
  "payment_order": [ payment_id, ... ],     # append order = seq order
  "requests": { request_id: {id, requester, payer, amount, note, status, payment_id, created_at, seq} },
  "splits":   { split_id: {...} },
  "settlements": { settlement_id: {...} },
  "idem":     { user_id: { "<METHOD> <path>\n<key>": {"canon": str, "status": 201, "body": {...}} } },
  "seq": int,                               # monotonic, one per created record
  "counters": { "p": int, "rq": int, "sp": int, "st": int, "u": int }
}
```

Rule for every module: state holds only JSON-native values (no tuples, sets, Decimals,
datetimes). That makes export a plain `json.dumps(state)` and import a validate-then-swap, and it
is the seam that lets `transfer_io.py` be built without knowing endpoint internals.

### Invariant enforcement — one place each

| Invariant | Enforced in | How |
|---|---|---|
| Sum of balances = seeded total | `store.apply_transfer` / `store.apply_batch` | Only these change `balance`; each debits and credits the same amount in one step under the lock. No other code writes `balance`. |
| No negative balance, even transiently | same two functions | Check `balance >= amount` (or, for a batch, every wallet's net result `>= 0`) and write, under the lock, with no I/O between. Batch applies only after the full net check passes. |
| A request moves money at most once | `requests_.pay` | Under the lock: status must be `pending`; transfer and `status = paid`, `payment_id` set in the same critical section. |
| Idempotent op takes effect once | `routes.dispatch` + `idempotency` | Resolve, execute and record in one lock hold (§5). |
| Handle uniqueness | `store` index `handles` | Insert under lock after checking the index. |
| No 5xx | `server.Handler` | Catch-all; all validation raises `ApiError`. |

## 2. Owner split

| Owner | Files | Items |
|---|---|---|
| Builder | `server.py`, `http_util.py`, `routes.py`, `errors.py`, `validation.py`, `store.py`, `testctl.py`, `auth.py`, `idempotency.py`, `payments.py`, `requests_.py`, `Dockerfile`, `RUN.md`, tests for those | S1.1–S1.4, S1.8 |
| Designer | `splits.py`, `settlements.py`, `transfer_io.py`, `tests/test_splits.py`, `tests/test_settlements.py`, `tests/test_transfer_io.py` | S1.5–S1.7 |

The seam is the interface column above. The designer's handlers register with the `@route`
decorator and get the lock, idempotency and auth for free from `routes.dispatch`; they move money
only through `store.apply_transfer` / `store.apply_batch` and create requests only through
`requests_.create_request`. `server.py` imports the three designer modules so registration happens;
until they exist the imports are guarded so S1.1–S1.4 run alone. Any change to the interface goes
through @lead.

## 3. Skeleton S1.1 (unblocks everyone)

`server.py`, `http_util.py`, `routes.py` (pipeline incl. auth + idempotency hooks as stubs),
`errors.py`, `store.py` (state, lock, `load_fixture`, `replace_state`, `apply_transfer`,
`payment_view`, `request_view`, clock, ids), `testctl.py` (`GET /health`, `POST /_test/reset`),
`tests/harness.py`, `Dockerfile`, `RUN.md`.

Reset (§3.3, §4 fixture): parse → validate the whole fixture into a fresh state object outside the
lock (currency string, `minor_units` ∈ {0,2,3}, users with unique id/handle/email, handle matches
`^[a-z0-9_]{1,20}$`, integer balance ≥ 0 else 422, payments/requests referencing known users,
request status in the four values, `settlement_operator_ids` default `[]` referencing known users)
→ hash passwords → swap under the lock → 204. A failed reset changes nothing. Seeded payments and
requests get `created_at` = reset time and `seq` in fixture order; seeded balances are used as given
(no replay).

## 4. Work items

Common DONE WHEN for every item (in addition to its own):
`cd stage-1 && python3 -m unittest discover -s tests -v` passes, and
`docker build -t builder-s1 stage-1 && docker run -d --rm --name builder-s1 -e PORT=18200 -p 18200:18200 --cpus 2 --memory 2g builder-s1`
then `curl -fsS localhost:18200/health` returns `{"status":"ok"}` within 60 s; `docker rm -f builder-s1`.

| Item | Owner | Spec | Scope | Item DONE WHEN |
|---|---|---|---|---|
| S1.1 Skeleton | Builder | §2, §3, §4 fixture, §5 envelope | as §3 above | tests: health 200; reset 204 then state = fixture; negative balance 422 and old state kept; malformed JSON 400; unknown route 404 envelope; `PORT` honoured |
| S1.2 Auth | Builder | §6, §4 handles, §8 `GET /me` | signup/login/me, tokens, scrypt hashing, handle derivation | tests: every row of the §6 table; seeded login; derived handle examples (`Ada.Lovelace+x@…` → `ada_lovelace_x`, truncation to 20); missing/unknown token 401; `/me` shape |
| S1.3 Idempotency + payments + activity | Builder | §7, §8 `POST /payments`, §8 `GET /activity`, §4 feed, §5 | key store, dispatch pipeline, payment, feed with limit/offset/has_more | tests: every §7 table row; 20 concurrent identical POSTs → one 201, rest 200, one debit; every `POST /payments` row; amount `1000`, `1000.0`, `1e3` valid, `true`/`"1000"` 422; note unicode round trip; feed rule for public/private × sender/receiver/third party |
| S1.4 Requests | Builder | §8 requests endpoints, §4 requests | create, pay, decline, cancel, list | tests: every row of each table; request > balance stays pending then payable after funding; concurrent pays of one request (different keys) → exactly one 201; `{}` vs `{"visibility":"public"}` reuse → 409; list filters, ordering, has_more |
| S1.5 Splits | Designer | §8 `POST /splits`, §9 | handler + share rule | tests: §9 table, order sensitivity, caller-only split → `requests: []`, zero shares produce requests, every error row, idempotent replay |
| S1.6 Settlements | Designer | §11 | operator check, batch validation in input order, collective affordability, `apply_batch`, `settlement_id` on all payment views | tests: 401/403, 1..32 bounds, entry error precedence, net-affordable batch where a wallet goes through zero, all-or-nothing, same `created_at` = `committed_at`, replay 200 |
| S1.7 Export/import | Designer | §10 | atomic snapshot, validate-then-swap import | tests: export→reset→import restores logins, tokens, balances, replays (200 same body), failed keys reusable; bad track/version/state 422 with state unchanged; double import no duplicates |
| S1.8 Load and limits | Builder | §2 limits, §5 "no 5xx", §1 invariants | concurrency soak in container | script `tests/soak.py` against the container: 50 in-flight mixed writes for 60 s → zero 5xx, sum of balances unchanged, no negative balance, p99 < 5 s; reset with 1 000 users < 10 s |

Order: S1.1 → (S1.2, S1.3) → S1.4 → S1.8. Designer starts S1.5–S1.7 once S1.1 and S1.3 are
accepted (they need the pipeline and `apply_transfer`); S1.7 is last because it must cover every
state key.

## 5. Request pipeline and idempotency

`routes.dispatch` runs these steps in this order for every request; the first failure answers.

1. Route match (404 / 405).
2. If `auth`: bearer token → user (401 `unauthenticated` if missing, malformed or unknown).
   Token lookup is a dict read; done under the lock.
3. If `operator`: user in `operators` else 403 `forbidden`.
4. Body: if the route takes a body, parse JSON; unparseable, `NaN`/`Infinity`, or not an object →
   400 `malformed_request`. An empty body on decline/cancel is treated as `{}`.
5. If `idempotent`: `Idempotency-Key` absent or empty → 400 `missing_idempotency_key`; longer than
   255 characters → 422 `validation_failed`.
6. **Acquire the lock.** If `idempotent`: `idempotency.resolve` — record exists for
   `(user_id, METHOD, path, key)`: same canonical body → return `(200, stored_body)`; different →
   409 `idempotency_key_reuse`.
7. Handler: field validation, resource checks, effect, returns `(201, body)`.
8. If `idempotent` and status is 201: `idempotency.record(...)` stores canonical body and response
   body. A 4xx is never recorded, so the key stays free (§7 "treated as a first use").
9. **Release the lock**, write the response.

Key scope: per user, then per `METHOD + path` (the concrete path, e.g. `/requests/rq_4/pay`), then
key string. Same key on a different path is a different record (§7).

Canonical body (`validation.canonical`): recursively convert the parsed value — `Decimal` that is
integral → `int`, non-integral `Decimal` → its normalised string tagged as a float — then
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. So key order and
whitespace do not matter, `1000`, `1000.0` and `1e3` compare equal, `true` ≠ `1`, and `{}` ≠
`{"visibility":"public"}`.

Concurrency: steps 6–8 hold the single lock, so for N concurrent identical requests the first to
acquire it executes and records; all others find the record and return 200 with the same body.
Check and write are never split across two lock holds anywhere in the service.

Password hashing is the one deliberate exception to "everything under the lock": signup hashes
before taking the lock, then inserts under the lock re-checking email and handle uniqueness; login
reads the stored hash under the lock and verifies outside it. Neither moves money.

## 6. Numbers and fields

- JSON is parsed with `parse_float=Decimal` so `1000.0000000001` is not silently rounded.
- `amount`: valid iff `type is int` (bool excluded explicitly) or a finite `Decimal` with integral
  value; then `1 ≤ amount ≤ 1_000_000_000`. Anything else — bool, string, null, fraction, out of
  range, missing — is 422 `validation_failed` (§5 endpoint rule; amounts never give 400).
- `note`: optional, default `""`; present and not a string (incl. `null`) → 422; length > 200
  code points → 422; stored verbatim.
- `visibility`: optional, default `"public"`; anything else (incl. `null`, wrong type) → 422.
- Other string fields (`to_handle`, `payer_handle`, `email`, `password`, `display_name`): missing →
  422; wrong JSON type → 400 `malformed_request`; a string handle not matching
  `^[a-z0-9_]{1,20}$` → 422 (§5 "invalid format"); well-formed but unknown → 404.
- Query integers (`limit`, `offset`): must match `^[0-9]+$` (so `1e9`, `4.0`, `+4`, `-1`, empty →
  422); `limit` 1..200 default 50, `offset` ≥ 0 default 0. `direction`, `status` must be one of
  their values when present (an empty value is 422). Unknown parameters ignored.
- Balances are Python `int` (arbitrary precision); no float ever touches money.

Endpoint check order (first failure answers): type errors (400) → field rules (422) →
`self_payment`/`self_request` (compare string to caller's handle) → unknown handle/resource (404) →
permission (403) → state (`request_not_pending` 409) → funds (`insufficient_funds` 409).

## 7. Timestamps and ordering

- `store.now_ts()` = `datetime.now(timezone.utc).isoformat(timespec="seconds")` →
  `2026-09-24T11:04:03+00:00` (RFC 3339 with explicit offset).
- Every created record also gets `seq` from the global counter, assigned under the lock.
- Lists sort newest first by `(created_at, seq)` descending, so same-second items are ordered by
  creation and pagination is deterministic for a quiescent state. Seeded items take the reset time
  and fixture order.
- Settlement members share one `created_at` = `committed_at`; their `seq` follows input order.

## 8. Build and run

`stage-1/Dockerfile`: `FROM python:3.12-alpine`, copy `app/`, `ENV PORT=8080 PYTHONUNBUFFERED=1`,
`EXPOSE 8080`, `CMD ["python", "-m", "app.server"]`. No pip installs, nothing fetched at run time,
starts in well under a second. `RUN.md` one command:
`docker build -t pocketful-s1 stage-1 && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1`,
plus the test command.

## 9. Decisions recorded (open choices settled here)

1. D1 Handle format on input: a string that cannot be a handle → 422, not 404.
2. D2 `pay` by any non-payer (requester or third party) → 403 per the endpoint table, after the 404
   for an unknown id.
3. D3 Email uniqueness is case-insensitive (`email_lc`); login matches case-insensitively; the
   stored email keeps its case. Email form: exactly one `@`, non-empty local and domain, no
   whitespace.
4. D4 Signup check order: field 422s → `email_taken` → `handle_taken`.
5. D5 Settlements: 401 → 403 → body → key → validation. Batch shape errors (transfers missing, not
   a list, size outside 1..32, entry not an object, entry handle of wrong type) are 422.
6. D6 Generated ids use counters with prefixes `u_`, `p_`, `rq_`, `sp_`, `st_` and skip any id
   already present (seeded ids may collide).
7. D7 Seeded passwords: scrypt (`n=2**14, r=8, p=1`) with a salt per distinct password per reset,
   so a fixture of many users sharing one password resets fast; signup uses a fresh salt per user.

## 10. Risks

| Risk | Mitigation |
|---|---|
| scrypt cost under 50 concurrent logins/signups on 2 vCPU | Hash outside the lock; `hashlib.scrypt` releases the GIL; S1.8 measures p99; drop to `n=2**13` if needed. |
| Reset with a large fixture beyond 10 s | Per-distinct-password hashing (D7); measured in S1.8. |
| One global lock limits throughput | Critical sections are dict operations (µs); 50 in flight is far below the limit. Correctness first. |
| `ThreadingHTTPServer` accept backlog / connection resets under burst | `request_queue_size = 1024`, daemon threads, HTTP/1.1 keep-alive with exact `Content-Length`, catch-all handler. |
| Ambiguous spec points (D1, D2, D5 order) disagree with acceptance tests | Decisions recorded above; @analyst can contest with a quote, fix is local to `validation.py` / one handler. |
| Designer modules drift from the state shape | State shape fixed in §1; S1.7 is last and validates every key. |
