# Stage 4 implementation plan — refunds and batch corrections

Packet: S4.P. Sources: `runlog/stage4-spec.md` on top of the stage 1–3 specs. Author: Builder.
Base: `stage-4/` = stage 3 accepted at `36547b6` (copied unchanged at `2cdac7b`; RUN.md
rewritten at `bb32d6a`). Everything in the stage 1–3 plans and decisions still holds: one
process, Python 3.12 stdlib, `python:3.12-alpine`, JSON-native state behind **one** lock entered
through `STORE.hold()` (expiry sweep first), parse outside the lock, the pipeline auth → operator →
body → key → replay → effect → record in one hold, D-41..D-61, L5–L9. Lead L10 (stage 4) and L11
apply.

## 0. Shape in one paragraph

A **refund** is an ordinary new payment in the opposite direction with `refund_of` set; it moves
existing money out of the receiver's available funds, and the refunded total of a payment is the
sum of its refunds' (immutable) amounts. A **correction batch** is many stage 3 corrections
validated together and applied in one lock hold: every proposed revision is built first, the
combined effect is checked against current available funds and against every historical boundary
of every affected wallet, and only then are all revisions appended with one shared `recorded_at`
and balances moved — so a rejection leaves nothing behind and concurrent writers serialise on the
lock. Statement snapshots become part of the export again (L10), stored as recipes when they read
the current state and as frozen rows otherwise.

## 1. Refunds

`POST /payments/{payment_id}/refunds` — idempotent (ninth path), body `{"amount": n}`.

Order (first failure answers; extends D-01/D-46):
401 → 400 body → 400/422 key → replay (200 original / 409 reuse) → 422 `validation_failed`
(`amount` integer 1..1 000 000 000, every defect incl. wrong type; D4-1) → 404 unknown payment →
403 caller is not the original receiver (sender and third parties alike) → 422
`invalid_refund_target` (the target is itself a refund) → 422 `refund_exceeds_payment`
(`refunded(target) + amount > current corrected amount`, i.e. the latest revision's amount) →
409 `insufficient_funds` (receiver's **available** < amount) → effect.

Effect (one hold): new payment `{from: target.to, to: target.from, amount, note and visibility
copied, request_id null, authorization_id null, settlement_id null, refund_of: target id,
created_at: tick}` with revision 1 (stage 3 rule), moving `amount` between the two wallets.
201 with the payment view; replay 200 with the stored body. Refunds never touch requests,
authorizations or holds, and never change settlement membership.

Model additions: `payments[pid]["refund_of"]` (null for every other payment; imports default it
to null); derived index `state["refunds_of"][target] = [refund ids]` rebuilt on reset/import;
`refunded(target) = Σ amounts of its refunds` (refund payments are immutable, so revision 1).
Payment views gain `refund_of` everywhere new payments are rendered (14 keys). Stored receipts of
earlier responses are replayed unchanged (as D11/D-47).

Allowed targets: direct payments, request payments, captures, settlement members (spec:
"A settlement payment may be refunded under the existing refund rules"). Seeded and imported
payments too.

## 2. Corrections in stage 4 (single, stage 3 path)

Unchanged stage 3 rules plus: captures **and refund payments** → 422 `linked_payment_immutable`;
settlement members stay 422 `linked_payment_immutable` on the single path ("Ordinary
single-payment corrections remain available for nonmembers"); a new amount below the payment's
refunded total → 422 `refund_exceeds_payment`. Order: … → 404 → 403 → 422 linked → 409
`stale_revision` → 422 `refund_exceeds_payment` → 409 `insufficient_funds` (available) → 409
`historical_overdraft` (D4-2). Refund payments enter every historical computation as ordinary
payments.

### Linked-rules matrix

| Target | Single correction (sender) | Correction batch (operator) | Refund (receiver) |
|---|---|---|---|
| Direct / request payment | allowed | allowed | allowed |
| Settlement member | 422 linked_payment_immutable | allowed — every member of that settlement, identical effective instants | allowed |
| Capture | 422 linked_payment_immutable | 422 linked_payment_immutable | allowed |
| Refund payment | 422 linked_payment_immutable | 422 linked_payment_immutable | 422 invalid_refund_target |
| Any, new amount < refunded total | 422 refund_exceeds_payment | 422 refund_exceeds_payment | — |

## 3. Correction batches

`POST /correction-batches` — idempotent (tenth path); settlement operator only: 401 without a
token, 403 `forbidden` for an authenticated non-operator (as settlements). Body
`{"corrections": [...]}`; unknown fields ignored.

**Validation pipeline** (D-66; all inside the one lock hold, before any write; first failure
answers). Before the items: 401 → 403 not an operator (no body needed) → 400 body → 400/422 key →
replay/reuse, then:
1. Shape: `corrections` an array of 1..32 objects; every `payment_id` a string, all distinct →
   else 422 `validation_failed`.
2. Item errors in input order. For each item, in this order: fields (as a single correction:
   `expected_revision`, `amount` 0..1e9, `effective_at` ≤ N, `reason` 1..200 → 422
   `validation_failed`) → 404 unknown payment → 422 `linked_payment_immutable` (capture or refund)
   → 409 `stale_revision` → 422 `refund_exceeds_payment`. The first item with any error decides.
3. Settlement checks, per settlement in order of its first member's appearance: every member
   must be in the batch → else 422 `incomplete_settlement`; then all of that settlement's items
   must share one effective instant (compared by key, offsets may differ) → else 422
   `validation_failed` (D-66).
4. Current available funds: net change per wallet over **all** items (Σ of `new − current` with the
   sender/receiver signs); every wallet whose net is negative needs `available + net ≥ 0` → else
   409 `insufficient_funds`.
5. Historical: for every affected wallet, with **all** proposed revisions selected (K = +∞), walk
   every distinct boundary ≤ N of selected effective times and hold events (same-instant changes
   combined), require total ≥ 0 and total − held ≥ 0 → else 409 `historical_overdraft`.
6. Commit: one `recorded_at` = one monotonic tick (strictly later than every previous recorded_at,
   including every member's), one `correction_batch_id`, append one revision per item (each
   carrying `correction_batch_id`), move each item's difference between its payment's two wallets,
   store the batch record, record the idempotent response. 201
   `{correction_batch_id, recorded_at, revisions: [...]}` in input order.

Steps 1–5 only read; step 6 cannot fail. That is the all-or-none guarantee, and the single lock
makes "Concurrent corrections sharing any expected payment revision cannot both succeed" hold for
any mix of single corrections and batches (the second sees `stale_revision`). No failure-injection
hook is needed; a test-only hook is not planned (D4-4).

Revision view (single corrections, batches, `/revisions`, statements' selection) gains
`correction_batch_id` (null for revision 1 and single corrections) (D4-5). Original payments,
receipts and settlement receipts never change; settlement retries return their original bodies;
earlier snapshot tokens keep paging their frozen entries (recipes select at K' ≤ their N, and the
batch's recorded_at is later).

State: `correction_batches[id] = {id, operator, recorded_at, payment_ids}`; counter `cb`.

## 4. Snapshots under L10

L10: "A stage-4 service must accept exports produced by the same team's stages 1–3, retaining
settlement membership, corrections and snapshots" → stage-4 exports carry snapshot tokens and
import restores them (overrides stage 3's L8 for stage 4).
- Live snapshots stay O(1) recipes. **Export** writes every token as its recipe
  `{user, start, end, known, known_echo}` (exact decimal strings). A recipe reading the exported
  state needs nothing more. Recipes that still read an older state (they survived an import, L12)
  carry a `generation`; each such state is exported **once** as a compact ledger view — the
  snapshot owners' payments with their revisions, the openings and handles involved, the
  currency — so the export grows with retained states, never with reads × window (verifier F9).
- **Import of a stage-4 export merges** its snapshots into the in-process store (lead L12, which
  amends D-74): recipes bind to the imported state or to their generation's view; destination
  tokens keep paging; on a clash the imported token wins. Importing a stage-1/2/3 export adds
  nothing. Reset clears everything.
- Tokens are opaque random strings and are carried verbatim (deterministic across export/import).
- **Stage-3-format imports** carry no snapshots (stage 3 L8 never exported them): nothing to
  restore; stage-3 tokens cannot survive that upgrade. Known limitation, recorded, not worked
  around (L10).
- Reset ends all snapshots.

## 5. Upgrade from stage 1–3 exports

Detection by structure: stage 1 (no `authorizations`), stage 2 (no `user_payments`/revisions),
stage 3 (revisions but no `refunds_of`/`correction_batches`), stage 4 (everything).
- Stage 1/2: as in stage 3 (revision 1 synthesis, openings, hold events with D-52 voids, L5
  sessions) plus `refund_of: null`, `correction_batch_id: null` on revisions, no batches, no
  snapshots.
- Stage 3: revisions, events and closed_at kept; `refund_of: null`; revisions' `correction_batch_id`
  null; settlement membership from `settlement_id`; no snapshots (limitation above); L5 session
  carry-over extended to stage-3-format imports (they are upgrades; D4-8, lead to confirm).
- Stage 4: pure round trip including snapshots, batches, refund index (rebuilt, not trusted).

## 6. Work items (builder)

Common DONE WHEN: unit tests green; image from a clean worktree healthy within 60 s on 18200–18299
with `--cpus 2 --memory 2g`; carried acceptance suites (stage 1–3) green; designer's oracle
`diff_run.py` no divergence; **RUN.md current for every item** (both commands run).

| Item | Scope | Item DONE WHEN |
|---|---|---|
| **S4.1 Refunds** (may start after this plan, L11) | §1, §2 refund rules for corrections, payment `refund_of` | tests: every error in order; partial refunds up to the corrected amount; refund after a correction; correction below refunded total 422; capture/settlement-member/request targets; refund of refund 422; available check incl. holds; replay; history/statements include refunds; Σ totals constant |
| S4.2 Correction batches | §3 | tests: shape, item-error precedence by position, completeness, identical effective instants across offsets, combined current and historical affordability (a batch that is affordable only together; one that fails only together), shared recorded_at, correction_batch_id on revisions, original receipts/settlement replays unchanged, old snapshots unchanged, 403/401, replay; concurrent batch vs single on a shared revision → one wins |
| S4.3 L10 snapshots in export | §4 | tests: token survives export → reset → import (pages identically), recipe vs frozen rows after an earlier import, shared rows, stage-3-format import has none, export size bounded by distinct results |
| S4.4 Upgrade over populated state | §5 | real frozen stage-1, -2 and -3 images, populated with every write kind incl. corrections; import; history, statements, refunds and batches on imported data; stage-4 round trip incl. snapshots |
| S4.5 Concurrency and load | all | stress: refund races on one payment (never over the corrected amount), batch races on shared revisions, batches vs refunds vs payments under 50 in flight, Σ totals in historical views, snapshots stable, no 5xx, < 5 s, flat memory |

Order: S4.1 → S4.2 → S4.3 → S4.4 → S4.5.

## 7. Decisions (binding: analyst D-62..D-75 at 200efad; lead L10, L11)

- D-62 refund order; D-73 refund amount rules (all defects 422) — my D4-1.
- D-63 cap = target's latest revision at the read instant.
- D-64/D-65 single path: members, captures, refunds → linked; stale before refund_exceeds — my D4-2.
- D-66 batch precedence incl. in-item order and per-settlement checks by first appearance — my D4-3.
- D-67 per-item difference between its own wallets; combined net per wallet for the checks.
- D-68/D-69 batch response; `correction_batch_id` on every revision object and statement entry
  (null unless a batch) — my D4-5.
- D-70 one lock: exactly one winner among overlapping single corrections and batches.
- D-71/D-72 a refund is an ordinary payment; `refund_of` on every new payment object (14 keys);
  stored receipts replay verbatim.
- D-74 + L12 upgrades and snapshots: stage-4 exports carry snapshots; importing one merges them
  into the store (imported token wins a clash); stage-1/2/3 imports add none; L5 sessions for
  stage-1/2/3 imports (my D4-8); stage-3 tokens cannot survive (limitation).
- D-75 carried suite changes.
- D4-4 revised (lead's plan-gate note): batches are prepare-then-apply — every object is built
  before the first write; a unit test injects a failure into the prepare step. D4-6 revised (F9):
  exported snapshots are recipes; retained older states are exported once as ledger views.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Combined affordability subtly differs from per-item checks | one function computes per-wallet nets and boundaries for any set of proposed revisions; tests with batches affordable only together and failing only together; oracle diff |
| Revision view shape change (correction_batch_id) breaks carried stage 3 assertions | D4-5 recorded; the analyst updates stage-3 copies if needed |
| Export size growth from snapshots (stage 3 F1 again) | recipes for current-state snapshots; frozen rows only for older generations, deduplicated |
| Stage-3 tokens lost on upgrade | L10 known limitation, recorded |
| Settlement completeness with members already refunded | refunds are separate payments; membership unchanged; floor check per member |
| RUN.md drift | part of every item's DONE WHEN |
