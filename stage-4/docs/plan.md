# Stage 3 implementation plan — statements and payment corrections

Packet: S3.P. Sources: `runlog/stage3-spec.md` on top of `runlog/stage2-spec.md` and
`runlog/stage1-spec.md` (§n = stage 1). Author: Builder. Base: `stage-3/` = stage 2 accepted at
`6a3fd33` (copied unchanged at `1a674f4`). Everything in the stage 1 and stage 2 plans still holds:
one process, Python 3.12 stdlib, `python:3.12-alpine`, JSON-native in-memory state behind **one**
lock entered through `STORE.hold()` (which sweeps clock expiry first), parse outside the lock,
pipeline auth → operator → body → key → replay → effect → record in one hold, D1–D14, L5.

Lanes: **builder** = API and model (`stage-3/app/**` except `web/` and `passwords.py`);
**designer** = an independent reference model plus differential and stress tooling, and any user-
visible history in existing screens; **analyst** = ledger and acceptance.

## 0. Shape in one paragraph

The ledger becomes **bitemporal**. A payment keeps its stage 1 record (receipts, activity and
idempotent responses never change) and gains an append-only list of **revisions**, each with
`amount`, `effective_at` (when the money counts) and `recorded_at` (when the service learned it).
Every user has an **opening balance**. Any historical view `(T = as_of, K = known_at)` is computed,
never stored: for each of the user's payments take the latest revision recorded at or before K;
apply those whose `effective_at` ≤ T (or inside a half-open window for statements) on top of the
opening balance. Holds get an **event log** (created, capture, release) with event times, and
`closed_at`, so `held` can be computed for the same view. Current balances stay materialised (as
today) and every write keeps them equal to the view `(now, now)`. A statement result is frozen in
memory under an opaque **snapshot** token.

## 1. Data model

### 1.1 Instants (decision S3-D1 — precision and representation)

- **Parsing**: an input instant must be RFC 3339 *with an offset* (`Z`/`z` or `±HH:MM`, `T`/`t`,
  any number of fractional digits). Anything else (naive time, bare date, empty, leap second
  `:60`, out of range) → 422 `validation_failed`.
- **Comparison key**: `ikey(s) -> Decimal` = exact seconds since the Unix epoch (integer part from
  the calendar date/time minus the offset, plus the fractional digits **exactly**, computed in a
  local `decimal` context with 60 digits of precision). No rounding anywhere; `19:00+02:00`
  equals `17:00Z`; `.5` equals `.500`.
- **Echo**: every *supplied* instant (`as_of`, `known_at`, a correction's `effective_at`) is
  echoed exactly as given (string kept).
- **Server-assigned instants** (new payments' `created_at`, `recorded_at`, hold events,
  `committed_at`, `closed_at`): **microsecond precision**, UTC, rendered
  `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`, from one **service-wide monotonic clock**
  `STORE.tick()` = `max(wall-clock µs, previous + 1 µs)` taken inside the lock. Every
  server-assigned instant is therefore unique and strictly increasing, so "Recorded times for one
  payment strictly increase" holds by construction and same-second ties among API-created
  payments disappear (stage 1/2 used whole seconds; still valid RFC 3339).
- **Seeded / imported** instants keep their string; the key is computed from it.

### 1.2 Payments and revisions

```
payments[pid] += {
  "revisions": [ {"revision": 1, "amount": int, "effective_at": str, "recorded_at": str,
                  "reason": str}, ... ]         # append-only, revision = index + 1
}
```
- Revision 1: `amount` = original amount, `effective_at = recorded_at = created_at`,
  `reason ""`. Created with the payment in the same hold (payments, request pay, settlements —
  members use the shared `committed_at`, which is their `created_at` — and captures).
- The stage 1 fields (`amount`, `created_at`, …) never change: `GET /activity`, receipts and
  stored idempotent responses keep showing the original payment (spec: "The original payment and
  every original idempotent response remain unchanged").
- `payment["latest"]` index and per-user index `state["user_payments"][uid]` (payment ids where
  the user is a party, append order) are derived caches rebuilt on reset/import (not trusted from
  input).

### 1.3 Opening balances

`users[uid]["opening"]`: the balance before anything moved.
- Reset: `opening = seeded balance − Σ signed seeded payment amounts` for that user. A negative
  opening, or a seeded history whose running balance goes negative at any boundary, contradicts
  "Seeded history is consistent and nonnegative" → 422 (decision S3-D2).
- Signup: 0. Import: recomputed as `balance − Σ signed latest amounts` (balances in an export are
  already net of everything), never trusted from input.
- Corrections never change openings.

### 1.4 Holds — event log

```
authorizations[aid] += {
  "events": [ {"kind": "created"|"capture"|"release", "at": str, "held_delta": int,
               "payment_id": str|null}, ... ],
  "closed_at": str | null
}
```
- created: `+amount` at `created_at`. Non-final capture: `−captured` at capture time (the capture
  payment's `created_at`). Final capture: `−captured` then `−remainder` (release) at the same
  instant. Void: release at void time. Expiry: release at `expires_at` (recorded when the sweep or
  an import sees it; its **effective** time is `expires_at`).
- `closed_at`: null while open; the closing event's time (expiry → `expires_at`). Exposed on every
  authorization response (new field, additive).
- Seeded **open** holds: created at their `created_at` if supplied, else reset time. Seeded
  **closed** holds have no lifecycle: they contribute no held at any instant ("need not
  reconstruct a prior lifecycle"). `closed_at` (D-51): expired → `expires_at`; captured or
  voided → supplied `closed_at`, else supplied `created_at`, else the reset instant.

## 2. Read algorithm — `GET /me` and `GET /statement`

Inputs: `T` (as_of; default = request start, `STORE.tick()` at the hold), `K` (known_at; default
= the same request start). Both may be in the future.

**Selection** `sel(p, K)`: the last revision with `ikey(recorded_at) ≤ ikey(K)` (revisions are in
recorded order, so a reverse scan stops at the first hit; usually 1–3 revisions). None → the
payment contributes nothing.

**Total at T** for user u:
`opening(u) + Σ_{p ∈ user_payments(u), r = sel(p,K), r ≠ None, ikey(r.effective_at) ≤ ikey(T)}
 sign(u,p) · r.amount` — inclusive `≤` for `as_of` (spec: "A payment made at exactly as_of counts").

**Held at T** for user u (payer side of holds): for each hold of u whose creation is known and has
happened (`created ≤ K` and `created ≤ T`): start at `amount`; apply each event with
`at ≤ T` **and** (`at ≤ K` or kind is expiry); if `T ≥ expires_at` and still holding, release
(the deadline is known once creation is known; "For queries beyond now, an open hold expires at
its deadline"). Result ≥ 0. `available = total − held`.

**/me response**: same shape as stage 2 plus, when supplied, `as_of` and `known_at` echoed
exactly; `balance = total`. Without either parameter the existing fast path (materialised
values) is used — equal to the view at (now, now) by invariant.

**Statement** (`from` default −∞, `to` default request start; half-open `[from, to)`):
1. For each of u's payments: `r = sel(p, K)`; skip None. Key `e = ikey(r.effective_at)`.
2. `opening_balance = opening(u) + Σ delta for e < from`; window entries: `from ≤ e < to`,
   sorted by `(e, payment id)` ascending (string order of ids); `balance_after` = running sum from
   `opening_balance` over **all** window entries; `closing_balance = opening_balance + Σ window
   deltas` (= balance immediately before `to`).
3. Entry = `{"payment": payment_view with amount = r.amount, "delta", "balance_after",
   "revision", "effective_at", "recorded_at"}`. Zero amounts give zero-delta entries.
4. The full result (window, `known_at`, resolved default `to`, balances, entries) is stored as a
   snapshot; the response is a page of it plus `snapshot`, `opening_balance`,
   `closing_balance`, `has_more`, and `known_at` echoed when supplied.

**Complexity**: O(P_u · R) per read for P_u = the user's payments and R revisions per payment,
plus O(P_u log P_u) to sort a statement. A user with 20 000 payments costs ~tens of ms. Paging a
snapshot is O(limit). All reads happen inside one lock hold (consistent view; the sweep runs
first).

**Validation**: `as_of`, `known_at`, `from`, `to` must parse (§1.1) else 422; empty → 422;
`from > to` → 422 (decision S3-D3); `limit`/`offset` as stage 1. With `snapshot`, any of `from`,
`to`, `known_at` present → 422; then unknown token / other user's token / pre-reset token → 404.

## 3. Correction write — `POST /payments/{id}/corrections`

Idempotent path (seventh+first: eight idempotent paths; same replay rules). Order, first failure
answers (extends D-01):

1. 401 → body 400 (unparseable / not an object) → key 400/422 → **replay** (stored 201 body →
   200, "even after newer revisions"; different body → 409 `idempotency_key_reuse`).
2. Fields (decision S3-D4: every invalid field, wrong type included, is 422, per "Invalid input is
   422 validation_failed"): `expected_revision` integer ≥ 1; `amount` integer 0..1 000 000 000;
   `effective_at` RFC 3339 with offset and `≤ now` (request start); `reason` string of 1..200
   characters (code points, D-05). All required.
3. 404 unknown payment. 403 caller is not the original sender (receiver and third parties).
4. 422 `linked_payment_immutable`: settlement member (`settlement_id` set) or capture
   (`authorization_id` set).
5. 409 `stale_revision`: `expected_revision ≠` latest revision number.
6. `diff = amount − latest.amount`. `diff > 0` debits the sender, `diff < 0` debits the receiver;
   409 `insufficient_funds` if the debited user's **current available** < |diff|.
7. 409 `historical_overdraft`: for the sender and the receiver (the only users whose history
   changes), with the new revision appended and `K = now`, build the boundary series of every
   distinct instant ≤ now among their selected effective times and hold events; group all
   movements at one instant; walk from `opening`; fail if `total < 0` or `total − held < 0` after
   any group. O(P_u log P_u).
8. Effect (same hold): append revision `{revision n+1, amount, effective_at as given,
   recorded_at = STORE.tick(), reason}`; move |diff| between the same two wallets' current
   balances; record the idempotent response; 201
   `{payment_id, revision, amount, effective_at, recorded_at, reason}`.

A failure at 4–7 leaves balances, revisions, statements, snapshots and idempotency state
untouched (checks happen before any write; one lock hold). Two concurrent corrections with the
same `expected_revision` serialise on the lock; the second sees `stale_revision`.

`GET /payments/{id}/revisions` → `{"revisions": [...]}` in revision order, revision 1 with
`reason: ""`. Parties only; third party → 404 (even public); no token → 401.

## 4. Snapshots (D-50, final L8; verifier S3.3 F1/F2)

- Process-wide store on the `Store` object, **not exported**: `token → recipe` with
  `{user, start, end (resolved to or N), known = min(known_at, N), known_echo, state}` where
  `state` is the ledger object the first read used. Token = `secrets.token_urlsafe(24)`.
- A snapshot page recomputes from the recipe. This reproduces the first result exactly because
  payments and revisions are append-only and never edited in place (unit-tested), and every later
  write is recorded after N, so selection at `known <= N` sees the same revisions; statements
  contain no hold events. O(1) memory per token; the export never grows with reads.
- Only reset ends snapshots. An import swaps in a new state object and leaves the store alone, so
  a token minted before an import keeps paging the state it read; that old state object stays
  reachable only through such recipes until the next reset. No cap, no eviction.

## 5. Upgrade and import

`format_version` stays 1 (D10). Import detects the source by keys:
- **stage-1 state** (no `authorizations`, no `revisions`): stage 2 defaults (as today) + revision 1
  for every payment from `created_at` (settlement members: their `committed_at` = `created_at`);
  openings recomputed; per-user indexes rebuilt; L5 session carry-over.
- **stage-2 state** (`authorizations`, no `revisions`): as above, plus hold events reconstructed:
  created at `created_at`; one capture event per `payment_ids` entry at that payment's
  `created_at`; closing: `captured` → last capture time; `expired` → `expires_at`; `voided` →
  **time unknown in a stage 2 export** → the latest of `created_at` and its last capture (the
  earliest consistent release; never creates a false `historical_overdraft`; decision S3-D7).
  L5 session carry-over also applies to a stage-2-format import (decision S3-D8, lead to
  confirm).
- **stage-3 state**: revisions, events, `closed_at` validated (revision numbers contiguous,
  recorded keys strictly increasing, amounts 0..1e9 except revision 1 which keeps the original,
  instants parse); openings recomputed and checked against the history; replacement as before.
- Snapshots are not exported (§4); the monotonic clock continues from `max(now, latest instant in
  the imported state + 1 µs)`.

## 6. Changes to existing endpoints

- `GET /activity`, payment receipts, replays: unchanged (original payment, original amount).
- New payments' `created_at`: microsecond precision (S3-D1); still RFC 3339 with offset.
- `GET /me`: unchanged without temporal parameters; with them, §2.
- Authorization views gain `closed_at`. Payment views unchanged (statement entries carry the
  selected amount inside `payment` and add `revision`, `effective_at`, `recorded_at`).
- Reset: seeded payment `created_at` in the future → 422; seeded holds may carry `created_at`
  (must not be in the future).

## 7. Work items (builder)

Common DONE WHEN: unit tests green; image from a clean worktree healthy on 18200–18299 with
`--cpus 2 --memory 2g`; carried acceptance suites (stage 1 and stage 2) green; stage 2 stress and
holds stress still pass.

| Item | Scope | Item DONE WHEN |
|---|---|---|
| **S3.1 Foundation** (may start before the gate) | `instants.py` (parse, ikey, monotonic tick), revisions on every payment path, openings, user indexes, hold events + `closed_at`, seeded `created_at` future → 422, seeded history consistency, export/import of the new keys, stage-1/2 synthesis (S3-D7) | unit tests: ikey exactness across offsets/fractions; every payment path writes revision 1; openings from seeded and imported states; hold events for create/capture/void/expiry; stage-1 and stage-2 exports import with revisions/events; stage-3 round trip equal |
| S3.2 `/me` as_of/known_at | §2 views incl. holds | tests for inclusive as_of, before-first = opening, after-last = current, known_at selection, future instants, hold lifecycle at T/K, echoes, 422s |
| S3.3 `/statement` + snapshots | §2, §4 | ordering (effective, id), half-open window, opening/closing identity, pagination invariance, snapshot freeze under writes/corrections, 404/422 rules, zero entries |
| S3.4 Corrections + revisions | §3 | every error with order, debit side, insufficient vs historical_overdraft (incl. available via holds and same-instant grouping), replay after newer revisions, concurrent same expected revision → one 201, linked immutability, revisions endpoint privacy |
| S3.5 Upgrade over populated state | §5 | real frozen stage-1 and stage-2 images, populated with every write kind incl. holds/captures/voids/expiries, export → stage-3 import → history views, statements, corrections, replays, tokens; stage-3 round trip |
| S3.6 Concurrency and load | concurrent corrections, statements and snapshots under writes; sum of totals in historical views | stress tool: no 5xx, < 5 s, Σ total(T,K) = seeded total for sampled views, snapshots unchanged under load |

Order: S3.1 → S3.2 → S3.3 → S3.4 → S3.5 → S3.6. The designer's reference model can start from
the spec and this plan; the API contract is §2–§3.

## 8. Decisions (binding: analyst D-41..D-60 at 754b18f; lead L7, L8)

Where this plan's first draft differed, the analyst's records and lead rulings win:
- Instants: D-41 (one service-wide monotonic µs clock under the lock, server instants rendered
  with 6 decimals and +00:00, unique and strictly increasing), D-42 (1–9 fractional digits,
  Z/z/T/t, exact comparison; a `+` decoded to a space in a query is repaired; the echo keeps the
  received string), D-43 (one read instant N per read; T = as_of or N, K = known_at or N).
  Seeded, imported and supplied instants are kept as their original strings.
- D-44 seeded created_at: future iff later than the reset instant R (payments, requests, holds).
- D-45 openings; reset rejects inconsistent or negative seeded history (my S3-D2).
- D-46 / D-57 / D-59 corrections: every field defect 422; order 401 → 400 body → 400/422 key →
  replay → 422 fields → 404 → 403 → 422 linked_payment_immutable → 409 stale_revision →
  409 insufficient_funds → 409 historical_overdraft (my S3-D4, S3-D9).
- D-47 revision shape `{payment_id, revision, amount, effective_at, recorded_at, reason}`.
- D-48 selection algorithm; D-49 statement shape; D-54 `from > to` → 422 (my S3-D3).
- D-50 + final L8: snapshots are process-wide recipes, not exported; only reset ends them; an
  import neither clears nor restores them; no cap (S3-D5/S3-D6 withdrawn).
- D-51 holds; seeded closed holds: closed_at = supplied, else expires_at (expired), else
  supplied created_at, else R.
- D-52 + L8: imports are not history-validated; voided stage-2 holds close at their last capture
  or created_at (S3-D7); L5 session carry-over for stage-1 **and** stage-2 imports (S3-D8);
  a stage-3 export is a pure round trip.
- D-53 historical_overdraft: both parties, boundaries ≤ N incl. hold events, total and available.
- D-58 effective_at ≤ N strictly. D-60 concurrency through the single lock.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Time semantics off by an edge (inclusive/exclusive, same-instant grouping, offsets) | one `ikey`; tests at exact boundaries; designer's independent reference model diffed against the service |
| Imported stage-2 voids lack a void time | S3-D7 (earliest consistent release); recorded |
| Snapshot memory growth | shared entry dicts; S3-D6 cap |
| Overdraft check cost on long histories | only two users per correction; O(P log P) |
| Stage 1/2 regressions (precision change of created_at) | carried suites must stay green; activity order unchanged (instant, seq) |
| Current vs historical drift | invariant test: view(now, now) == materialised values after every write kind |
