# Stage 2 implementation plan — wallet screens and payment authorizations

Packet: S2.P. Sources: `runlog/stage2-spec.md` (stage 2) on top of `runlog/stage1-spec.md`
(cited as §n). Author: Builder. Stage 1 (frozen at `9d7ab5e`) is the base: everything in its plan
still holds — one process, Python 3.12 stdlib, `python:3.12-alpine`, JSON-native in-memory state
behind **one** `threading.Lock`, the request pipeline (parse outside the lock, then auth → operator
→ body → key → replay → effect → record in one hold), decisions D1–D7, no runtime network.

Lanes: **builder** = API, model, export/import, the HTML/static seam; **designer** = screens
(`stage-2/web/**`); **analyst** = ledger and acceptance.

## 0. Shape in one paragraph

Holds are a new table, `authorizations`, plus a per-user `held` counter that is changed only in
`store.py`, in the same lock hold as the authorization's status change. Clock expiry is made
observable by a **sweep** that runs at the start of every lock hold (and before export): every open
authorization whose `expires_at` is at or before now becomes `expired` and its remainder is
released. Because nothing reads or writes state except inside a lock hold that began with a sweep,
"reads and writes reflect expiry even if no request occurred at the deadline" holds by
construction. `available = total − held` is computed on read; every `insufficient_funds` check
compares against it. Browser routes return files from `stage-2/web/` that the designer owns; the API
stays JSON.

## 1. State additions (store.py) and derivation

```
state += {
  "settings": {"authorization_ttl_seconds": 600},
  "authorizations": { auth_id: {
      id, from, to, amount, captured, note, visibility,
      status,               # open | captured | voided | expired
      expires_at,           # RFC 3339 string, as given or created_at + ttl
      created_at, seq,
      payment_ids: [ ... ]  # every capture, in order
  } },
  "counters": {..., "a": int}
}
users[uid] += {"held": int}            # sum of remaining amounts of this user's open holds
payments[pid] += {"authorization_id": str | null}
```

- `remaining(a) = a.amount − a.captured` while `open`, else `0`.
- `held(u)` = `users[u]["held"]`, maintained by the only four transitions that change it:
  create (+amount), capture (−captured part, and −remainder if final), void (−remainder),
  expire (−remainder). Reset and import **recompute** it from the authorizations table; an
  imported `held` is never trusted.
- `total(u) = balance(u)` (stage 1 field, unchanged meaning); `available(u) = total − held`.
- **Sweep** `store.expire_due(state, now)`: a min-heap of `(expires_instant, auth_id)` lives on the
  `Store` object (not in state; rebuilt by `replace_state`). Each lock hold pops every due entry;
  an entry whose authorization is still `open` becomes `expired` and releases its remainder.
  Cost: O(log n) per expiry, O(1) when nothing is due. `routes.dispatch`, the `locked=False`
  handlers (signup/login/reset/import/export) and `GET /me` all go through `STORE.hold()`, a
  context manager = `with lock: expire_due(...)`. That makes one place responsible for expiry.
- Instants are compared with `store.instant()` (already used for ordering), so any RFC 3339
  offset works. `expires_at` at or before now = expired (inclusive, per spec).
- The clock is `store.now()` (UTC); tests may monkeypatch it in-process. Black-box tests use a
  fixture `authorization_ttl_seconds: 1`.

Invariants and where each is enforced (one place each):

| Invariant | Place |
|---|---|
| Σ total = seeded total | `apply_transfer`, `apply_batch`, `apply_capture` — the only balance writers |
| available ≥ 0 | `place_hold` (checks `available ≥ amount`), `apply_transfer` and `apply_batch` (check against available); captures spend held money only |
| Σ captures ≤ authorized; each capture once; closed hold never captured | `apply_capture`: status `open`, not expired, `amount ≤ remaining`, in one hold with the idempotency record |
| Expiry visible on every read/write | `STORE.hold()` sweep |

## 2. insufficient_funds against available

| Site | Stage 1 check | Stage 2 check |
|---|---|---|
| `POST /payments` (`apply_transfer`) | `balance ≥ amount` | `balance − held ≥ amount` |
| `POST /requests/{id}/pay` (`apply_transfer`) | same | same |
| `POST /settlements` (`apply_batch`, designer's handler unchanged) | `balance + net ≥ 0` per wallet | `balance − held + net ≥ 0` per wallet |
| `POST /authorizations` (`place_hold`) | — | `balance − held ≥ amount` |
| capture | — | none: it spends its own hold (`held` and `balance` drop together) |

With no open holds `held = 0`, so every stage 1 result is unchanged.

## 3. Authorization endpoints (new module `app/authorizations.py`, builder)

View (`store.authorization_view`): `authorization_id, from_user_id, from_handle, to_user_id,
to_handle, amount, captured_amount, remaining_amount, currency, note, visibility, status,
expires_at, payment_id (latest capture or null), payment_ids, created_at`.
Payment view gains `authorization_id` (null unless a capture), so every payment body has 13 keys.

**`POST /authorizations`** (idempotent; caller = payer). Order (D-01 extended): 401 → body 400 →
key 400/422 → replay → `to_handle` type 400 / missing 422 → `amount` 422 → `note` 422 →
`visibility` 422 → handle format 422 → `self_payment` 422 → 404 → `insufficient_funds` 409
(available). Effect: `place_hold` creates the record, `held += amount`,
`expires_at = created_at + ttl`, heap push. 201. Never a feed item (activity lists payments only).

**`POST /authorizations/{id}/capture`** (idempotent; receiver only). Body `{amount?, final?}`.
Order: 401 → body 400 → key → replay → `amount` present and invalid → 422 `validation_failed`
(below 1, not integral, bool, string) → `final` present and not a boolean → 400
`malformed_request` (wrong JSON type, §5) → 404 unknown → 403 caller is not the receiver (incl.
non-parties) → 409 `authorization_expired` if status is `expired` (by sweep or clock) → 409
`authorization_not_open` if `captured` or `voided` → 422 `capture_exceeds_authorization` if
`amount > remaining` → effect. Decision **D8**: an authorization the clock has expired answers
`authorization_expired`, never `authorization_not_open`, on capture, whether or not a sweep has
already marked it.

Effect `apply_capture(a, amount, final)`: payer `balance −= amount`, receiver `balance += amount`,
payer `held −= amount`; `captured += amount`; append payment id; if `final` or `captured ==
amount`: status `captured`, payer `held −= remainder` (release). Payment: `amount`, `note` and
`visibility` copied, `authorization_id` set, `request_id` null, appears in the feed by the
ordinary rule. Returns 201 with the payment. Default `amount` = remaining; default `final` = true.
Replay → 200 with the original body (stored response, §7), no further effect. `{}` and
`{"amount": 2000}` canonicalise differently → 409 `idempotency_key_reuse`.

**`POST /authorizations/{id}/void`** (payer only, no key). Order: 401 → body 400 (empty body ok)
→ 404 → 403 → `voided` → 200 current state (repeat is fine) → `captured` or `expired` → 409
`authorization_not_open` → open: release remainder, status `voided`, 200. A partially captured
authorization keeps its captures and payment ids.

**`GET /authorizations`** (JSON API; HTML when `Accept` asks for it, §6). Caller is payer or
receiver only; `direction` outgoing|incoming, `status` one of four (clock-expired matches
`expired` only — the sweep guarantees it), `limit`/`offset`/`has_more` via the shared `page()`,
newest first via `store.newest_first`. Body `{"authorizations": [...], "has_more": bool}`.

`GET /me` adds `total` (= `balance`), `available`, `held`.

## 4. Fixture validation (reset)

- `authorization_ttl_seconds`: absent → 600; else integral (bool excluded), 1 ≤ n ≤ 10⁹
  (an upper bound keeps datetime arithmetic finite; D9), else 422.
- `authorizations`: absent → `[]`; each entry: unique `id` (≤64 chars), `from_user_id` and
  `to_user_id` known and different, `amount` 1..10⁹, optional `captured_amount` 0..amount
  (default 0), `note` string ≤200 (default ""), `visibility` public|private (default public),
  `status` one of four (required), `expires_at` RFC 3339 with offset (required), optional
  `created_at` (RFC 3339, default reset time), optional `payment_id`/`payment_ids`.
- Seeded `balance` is `total`. Per user, Σ remaining of **open and unexpired** seeded holds >
  balance → 422 `validation_failed`, nothing changes. Seeded `open` with past `expires_at` is
  swept to `expired` at load and holds nothing. `available` is never seeded.
- Every 422 leaves the previous state in place (validate-then-swap, as stage 1).

## 5. Export / import

- **D10** `format_version` stays `1`: §10 fixes `track: "pocketful", format_version: 1`, and a
  stage-2 service must accept a stage-1 export unchanged. The state object is opaque and gains
  keys; import treats them as optional with defaults.
- **Migration on import** (stage-1 state → stage-2 state): missing `settings` → ttl 600; missing
  `authorizations` → `{}`; missing `counters.a` → 0; payments without `authorization_id` → null;
  users' `held` recomputed from authorizations (0 for a stage-1 export). Tokens, idempotency
  records, replay bodies, ids, timestamps and balances are carried unchanged.
- **D11** replay of a pre-upgrade receipt returns the **stored original body unchanged**, i.e.
  without `authorization_id` — §7 "body identical to the original response as a JSON value"
  outranks the stage 2 shape note, which describes newly created payments. GET endpoints render
  migrated payments with `authorization_id: null`.
- Export runs a sweep first, then snapshots under the same hold.
- Ownership: `transfer_io.py` was the designer's in stage 1. Since the designer is on screens and
  this migration is model work, I propose the builder owns `stage-2/app/transfer_io.py` for stage
  2 (lead to confirm). Same for `settlements.py` and `splits.py` if their checks need changes;
  only `apply_batch` changes, which is mine.

## 6. HTML / static seam (item S2.1 — first, unblocks the designer)

- **Page routes** (GET and HEAD): `/`, `/split`, `/signup`, `/login` always HTML;
  `/requests` and `/authorizations` return HTML when the `Accept` header lists `text/html`
  with q > 0, else the existing JSON API (API clients and `fetch` with
  `Accept: application/json` keep JSON; `*/*` alone is JSON). Pages need no token: the shell
  authenticates in the browser with the bearer token it keeps (`localStorage`), which survives an
  import because tokens do (§10).
- **What a page route serves**: `web/<name>.html` if it exists (`index.html` for `/`,
  `split.html`, `signup.html`, `login.html`, `requests.html`, `authorizations.html`), else
  `web/index.html` (single-page shell). The designer chooses either pattern.
- **Static assets**: `GET /assets/<path>` from `stage-2/web/assets/`. Path is URL-decoded,
  normalised and must stay inside the folder (no `..`, no absolute paths, no NUL) → else 404
  JSON envelope. Types by extension: `.html` `text/html; charset=utf-8`, `.css` `text/css;
  charset=utf-8`, `.js`/`.mjs` `text/javascript; charset=utf-8`, `.json`, `.svg`
  `image/svg+xml`, `.png`, `.ico`, `.woff2` `font/woff2`; unknown → `application/octet-stream`.
- **Caching**: HTML `Cache-Control: no-cache`; assets `Cache-Control: no-cache` plus `ETag`
  (sha256 of content) and `304` on `If-None-Match`. Files are read once and cached in memory
  (they are in the image; no runtime network).
- **Headers on HTML**: `Content-Security-Policy: default-src 'self'; img-src 'self' data:;
  style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **Seam module** `app/web.py` (builder): registers page and asset routes with `auth=False,
  locked=False`; the `Dockerfile` copies `web/`. The designer writes only under `stage-2/web/`.
- **API contract for the screens** (stable, JSON): every stage 1 endpoint plus §3 above; the
  UI's `fetch` sends `Accept: application/json` and `Content-Type: application/json`. The pay
  form's retry identity (same key + same body) is the client's job; the server's §7 replay gives
  the original body. Amount parsing (decimal → minor units) and split preview (§9 rule) are
  client-side; `GET /me` gives `minor_units` and `currency`.

## 7. Work items (builder)

Common DONE WHEN for every item: `cd stage-2 && python3 -m unittest discover -s tests` green;
image builds from a clean worktree and is healthy within 60 s on a port in 18200–18299 with
`--cpus 2 --memory 2g`; stage-2 acceptance suite (analyst) green for the item's rows;
`stage-2/tools/stress.py` 8/8 still passes.

| Item | Spec | Scope | Item DONE WHEN |
|---|---|---|---|
| **S2.1 HTML/static seam** (first) | Stage 2 routes table, "browser and the API share /requests", UI `/authorizations` | `app/web.py`, Accept negotiation, `/assets/*`, Dockerfile copies `web/`, placeholder `web/index.html` until the designer's lands | tests: each page route → 200 `text/html`; `/requests` and `/authorizations` with `Accept: text/html` → HTML, with `*/*`/JSON → JSON (401 without token); traversal (`/assets/../app/store.py`, `%2e%2e`, `%00`) → 404 envelope; ETag/304; HEAD works |
| S2.2 Holds model | Authorizations model, invariants 1–3, GET /me, fixture | state additions, `STORE.hold()` sweep, `held`, available-based checks in `apply_transfer`/`apply_batch`, fixture rules, payment `authorization_id`, `/me` fields | tests: seeded open hold → `/me` available/held; seeded holds > balance → 422 unchanged; past `expires_at` → expired at load; ttl rules; payments/request pay/settlement refused against available; no-holds behaviour identical to stage 1 |
| S2.3 Authorize + list | `POST /authorizations`, `GET /authorizations` | handler, view, list filters | every table row; not in `/activity`; direction/status/paging; expiry by clock without any request at the deadline (ttl 1 s) |
| S2.4 Capture + void | capture (default and extended), void | `apply_capture`, D8 order, remainder release, `payment_ids`, `remaining_amount` | every table row; partial final capture releases remainder in the same step; `final:false` chain to exhaustion; `{}` vs `{"amount":n}` → reuse 409; 50 concurrent captures (distinct keys) never exceed the authorized amount; void then capture 409; expiry after partial capture keeps captures |
| S2.5 Export/import migration | §10 + "Existing clients after an upgrade" | defaults for missing keys, held recompute, D10/D11 | a real stage-1 export (from the frozen stage-1 image) imports into stage 2: logins/tokens work, pending requests payable, a pre-upgrade payment key replays 200 with the original body; stage-2 export→import→export equal |
| S2.6 Concurrency and load | "Concurrent operations…", §2 limits | stress scenarios for holds (authorize/capture/void/expiry races, settlements vs holds) in `tests/soak.py` and a stress extension | 50 in flight, 0 5xx, Σ total constant, available ≥ 0 at every sampled read, captures ≤ authorized |

Order: S2.1 → S2.2 → S2.3 → S2.4 → S2.5 → S2.6. The designer can start on S2.1's seam and the
stage 1 API at once; `/authorizations` screens need S2.3/S2.4.

## 8. Decisions recorded

- D8 capture of a clock-expired authorization → 409 `authorization_expired`; void of it → 409
  `authorization_not_open` (spec: "A captured or expired one is 409 authorization_not_open").
- D9 `authorization_ttl_seconds` upper bound 10⁹ → otherwise 422.
- D10 export `format_version` stays 1; stage-2 state keys are optional on import.
- D11 pre-upgrade replays return the stored body unchanged (no `authorization_id`).
- D12 `final` of the wrong JSON type → 400 `malformed_request`; invalid `amount` → 422.
- D13 `Accept` negotiation: HTML only when `text/html` is listed with q > 0; `*/*` alone → JSON.
- D14 seeded `captured_amount` > `amount`, or `from == to`, → 422.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Sweep missed on some path → stale `open` read | Single entry `STORE.hold()`; unit test asserts every route registers through the pipeline; expiry tests with ttl 1 s and no request at the deadline |
| `held` drifts from the authorizations table | Only four transitions write it, all in `store.py`; reset/import recompute; S2.6 checks `held == Σ remaining` after load |
| Stage-1 export shape vs stage-2 import | S2.5 test imports an export produced by the real frozen stage-1 image, not a hand-made one |
| Accept negotiation breaks API clients of `/requests` | `*/*` and absent → JSON; acceptance stage 1 suite re-run on stage 2 |
| Static path traversal | normalise + containment check + tests |
| Error-order ambiguities (D8, D12) disagree with acceptance | recorded here; each is a one-line change |
| Host CPU contention makes hashing slow (seen at the stage 1 gate) | unchanged from stage 1 (designer's bounded hashing); not touched here |
