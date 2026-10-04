# Stage 4 requirements ledger — Pocketful: refunds and batch corrections

Sources of truth: `runlog/stage4-spec.md` (stage 4) on top of `runlog/stage3-spec.md`,
`runlog/stage2-spec.md`, `runlog/stage1-spec.md` ("All requirements from stages 1–3 continue to
apply"). Earlier ledgers stay in force: stage 1 (228 rows, `stage-1/docs/ledger.md`), stage 2 (182
rows, `stage-2/docs/ledger.md`), stage 3 (128 rows, `stage-3/docs/ledger.md`, frozen 36547b6).
Rows stage 4 changes are listed in **Part B**. Open points are settled in D-62…D-75 and the lead's
L10 (snapshots in stage-4 exports).

- **id**: `R4-<area>.<n>`. Areas: PATH idempotent paths, REF refund endpoint, RSH refund payment
  shape and effects, RCOR single corrections after stage 4, BAT batch request and validation, BERR
  batch error precedence, BMNY batch money and history, BRES batch response and revisions, SET
  settlements under stage 4, CONC concurrency and atomicity, UPG upgrades and snapshots.
- **kind**: behaviour, error, invariant, limit, format, operational.
- **proof**: planned test in `stage-4/acceptance/stage4/` named `test_R4_<AREA>_<n>_...`; `prop:` =
  differential test against the analyst's reference model (stage 3 model extended with refunds and
  batches).
- **H** = hidden (unlikely to be probed by a quick reading or the event's shipped subset).

## Part A — new stage 4 requirements

### Idempotent paths (PATH)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-PATH.1 **H** | intro | "There are ten idempotent write paths: stage 1's five, authorizations and captures from stage 2, corrections from stage 3, and refunds and correction batches in this stage." | behaviour | test_R4_PATH_1_replay_rules_refunds_and_batches (missing key 400, length 422, replay 200 identical, reuse 409, claimed key before validation, failed-4xx key reusable, per-user, per-path, 20 concurrent identical → one 201) |
| R4-PATH.2 **H** | Refunds | "requires an idempotency key." | error | test_R4_PATH_1_replay_rules_refunds_and_batches |
| R4-PATH.3 **H** | Batch | "This adds one idempotent write path." / "Replays return the original batch response with 200." | behaviour | test_R4_BRES_6_replay_original_batch_response |

### Refund endpoint (REF)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-REF.1 | Refunds | "Recipients can refund payments." / "`POST /payments/{payment_id}/refunds`, body `{\"amount\": 200}`" | behaviour | test_R4_REF_1_receiver_refunds_201 |
| R4-REF.2 | Refunds | "Only the original receiver may refund, else 403 `forbidden`" | error | test_R4_REF_2_sender_and_third_party_403 (operator too) |
| R4-REF.3 | Refunds | "unknown payment is 404." | error | test_R4_REF_3_unknown_404 |
| R4-REF.4 **H** | Refunds | "The target may be a direct payment, request payment or capture" | behaviour | test_R4_REF_4_targets_direct_request_capture |
| R4-REF.5 **H** | Refunds | "but never a refund." / "Refunds of refunds give 422 `invalid_refund_target`." | error | test_R4_REF_5_refund_of_refund_422 |
| R4-REF.6 **H** | Refunds | "Invalid amount is 422 `validation_failed`." | error | test_R4_REF_6_amount_rules (0, −1, 1e9+1, 2.5, "5", true, null, missing → 422; 1e3 accepted) (D-73) |
| R4-REF.7 **H** | Refunds | "Refunds cumulatively may not exceed the payment's current corrected amount: 422 `refund_exceeds_payment`." | error | test_R4_REF_7_cumulative_cap_uses_corrected_amount (after a correction down and up; exact remainder ok, +1 → 422) (D-63) |
| R4-REF.8 **H** | Refunds | "It moves existing money from the receiver's **available** funds, or fails 409 `insufficient_funds`, atomically." | error | test_R4_REF_8_available_not_total (held funds don't count; failure leaves nothing) |
| R4-REF.9 **H** | derived, D-62 | refund error order: 401 → 400 body → 400/422 key → replay/reuse → 422 amount → 404 → 403 → 422 invalid_refund_target → 422 refund_exceeds_payment → 409 insufficient_funds | error | test_R4_REF_9_precedence_pairs |
| R4-REF.10 **H** | derived, D-64 | a settlement member may be refunded by its receiver | behaviour | test_R4_SET_1_member_refund_keeps_membership |

### Refund payment shape and effects (RSH)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-RSH.1 | Refunds | "A refund is a new payment in the opposite direction" | behaviour | test_R4_RSH_1_opposite_direction_and_balances |
| R4-RSH.2 **H** | Refunds | "with `refund_of` naming the target, `request_id: null`, `authorization_id: null`, and the original note/visibility." | format | test_R4_RSH_2_refund_fields (refund of a request payment and of a capture: both links null; note and visibility copied, incl. private) (D-71) |
| R4-RSH.3 | Refunds | "Return 201 with that payment; replay returns 200 with the original body." | behaviour | test_R4_RSH_3_replay_200_original_even_after_more_refunds |
| R4-RSH.4 **H** | Refunds | "Refunds never reopen a request or authorization or restore a released hold." | invariant | test_R4_RSH_4_no_reopen (request stays paid; authorization status, captured_amount, held unchanged) |
| R4-RSH.5 **H** | Refunds | "Other payments have `refund_of: null`." | format | test_R4_RSH_5_refund_of_null_on_every_payment_surface (payments, request pay, captures, members, /activity, statement entries) (D-72) |
| R4-RSH.6 **H** | derived, D-71 | a refund is an ordinary payment for the feed (visibility rule), statements (entry with its own revision 1 at created_at), as_of/known_at views and revisions | behaviour | test_R4_RSH_6_refund_in_feed_statement_and_history |
| R4-RSH.7 **H** | Refunds | "Captures and refund payments cannot themselves be corrected: 422 `linked_payment_immutable`." | error | test_R4_RSH_7_refund_and_capture_not_correctable |
| R4-RSH.8 **H** | derived, D-72 | stored receipts created before stage 4 (and imported ones) replay verbatim, without `refund_of` | behaviour | test_R4_UPG_4_old_receipts_replay_verbatim |

### Single corrections after stage 4 (RCOR)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-RCOR.1 | Refunds | "Stage-3 corrections remain available for ordinary direct/request payments." | behaviour | carried stage-3 suite + test_R4_RCOR_1_single_correction_still_works |
| R4-RCOR.2 **H** | Refunds | "A correction cannot reduce a payment below its already-refunded amount: 422 `refund_exceeds_payment`." | error | test_R4_RCOR_2_floor_at_refunded (equal ok, one below → 422) |
| R4-RCOR.3 **H** | Refunds | "Correction debits are checked against available funds." | error | test_R4_RCOR_3_available_not_total |
| R4-RCOR.4 **H** | derived, D-65 | single-correction order: … 403 → 422 linked (capture, refund, settlement member) → 409 stale → 422 refund_exceeds_payment → 409 insufficient → 409 historical | error | test_R4_RCOR_4_precedence (stale beats refund_exceeds) |
| R4-RCOR.5 **H** | Batch | "Ordinary single-payment corrections remain available for nonmembers." — members stay 422 `linked_payment_immutable` on the single path | error | test_R4_RCOR_5_member_single_correction_still_422 (D-64) |

### Batch request and validation (BAT)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-BAT.1 | Batch | "Settlement operators can correct several payments in one request, including payments that belong to a settlement." | behaviour | test_R4_BAT_1_operator_corrects_settlement_and_ordinary |
| R4-BAT.2 | Batch | "`POST /correction-batches` requires a settlement operator and an idempotency key, with the same 401/403 rules as settlements." | error | test_R4_BAT_2_401_403_and_key (403 before body, D-01) |
| R4-BAT.3 | Batch | body `{"corrections": [{"payment_id", "expected_revision", "amount", "effective_at", "reason"}]}` | format | test_R4_BAT_1_operator_corrects_settlement_and_ordinary |
| R4-BAT.4 **H** | Batch | "corrections contains 1..32 objects with distinct payment_ids, else 422 `validation_failed`." | limit | test_R4_BAT_4_count_and_distinct (0, 33, duplicate id, not an array, element not an object → 422; 32 ok) |
| R4-BAT.5 **H** | Batch | "Every item has the ordinary correction fields and validation." | error | test_R4_BAT_5_item_field_rules (each field missing/invalid/wrong type → 422; effective_at in the future → 422) |
| R4-BAT.6 | Batch | "Unknown payment is 404; a stale expected revision is 409 `stale_revision`." | error | test_R4_BAT_6_unknown_404_stale_409 |
| R4-BAT.7 **H** | Batch | "The operator may correct ordinary, request and settlement payments" | behaviour | test_R4_BAT_7_operator_needs_not_be_party |
| R4-BAT.8 **H** | Batch | "but captures and refunds remain immutable." | error | test_R4_BAT_8_capture_or_refund_item_422_linked |
| R4-BAT.9 **H** | Batch | "Correcting any settlement member requires including every member of that settlement, else 422 `incomplete_settlement`." | error | test_R4_BAT_9_incomplete_settlement_422 |
| R4-BAT.10 **H** | Batch | "Members of one settlement must have identical effective instants (offset spellings may differ), else 422 `validation_failed`." | error | test_R4_BAT_10_member_instants_identical_by_instant (`Z` vs `+02:00` same instant ok; 1 µs apart → 422) |
| R4-BAT.11 | Batch | "Unknown fields are ignored." | behaviour | test_R4_BAT_11_unknown_fields_ignored (top level and items) |
| R4-BAT.12 **H** | Batch | "Effective times cannot be later than now." | error | test_R4_BAT_5_item_field_rules |
| R4-BAT.13 **H** | derived, D-67 | an item whose new amount is below the payment's refunded total → 422 `refund_exceeds_payment` (item error) | error | test_R4_BAT_13_refund_floor_in_batch (settlement member refunded, then batch reversal → 422) |

### Batch error precedence (BERR)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-BERR.1 **H** | Batch | "Error precedence is: item errors in input order, settlement completeness, resulting current available funds, then historical total and available funds at every effective/event boundary." | error | test_R4_BERR_1_precedence_matrix (pairwise: item error beats incomplete; incomplete beats insufficient; insufficient beats historical; first erroneous item wins) (D-66) |
| R4-BERR.2 **H** | Batch | "The existing codes apply: `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`." | error | test_R4_BERR_1_precedence_matrix |
| R4-BERR.3 **H** | derived, D-66 | within one item: 422 fields → 404 → 422 linked → 409 stale → 422 refund_exceeds_payment; batch shape (count, distinct, element type) before any item | error | test_R4_BERR_3_within_item_order |

### Batch money and history (BMNY)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-BMNY.1 **H** | Batch | "Affordability is determined by the combined effect of all proposed revisions." | behaviour | test_R4_BMNY_1_combined_effect (a batch affordable only net: A gains from item 1 what item 2 debits) |
| R4-BMNY.2 **H** | Batch | "resulting current available funds" — current available after all deltas ≥ 0 for every wallet, else 409 `insufficient_funds` | error | test_R4_BMNY_2_insufficient_combined |
| R4-BMNY.3 **H** | Batch | "historical total and available funds at every effective/event boundary" → 409 `historical_overdraft` | error | test_R4_BMNY_3_historical_overdraft_combined (incl. holds) |
| R4-BMNY.4 **H** | Batch | "A rejected batch leaves history, balances and idempotency records unchanged." | invariant | test_R4_BMNY_4_rejection_changes_nothing (balances, /revisions, statements, the key reusable) |
| R4-BMNY.5 **H** | derived, D-67 | each item moves its difference between that payment's two wallets (sender ↑ debit / receiver ↓ debit); Σ totals = seeded total in every view | invariant | prop: test_R4_BMNY_5_model_every_view |

### Batch response and revisions (BRES)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-BRES.1 | Batch | "Return 201 with `correction_batch_id`, `recorded_at` and `revisions` in input order." | format | test_R4_BRES_1_shape_and_order (D-68) |
| R4-BRES.2 **H** | Batch | "All new revisions share recorded_at, strictly later than the previous recorded_at of every member" | invariant | test_R4_BRES_2_shared_recorded_at_strictly_later |
| R4-BRES.3 **H** | Batch | "each revision also exposes correction_batch_id." | format | test_R4_BRES_3_batch_id_on_revisions_everywhere (batch response, /revisions; single-correction and revision 1 → null) (D-69) |
| R4-BRES.4 **H** | Batch | "Original payments and receipts never change. Original payment and settlement retries return their original bodies." | invariant | test_R4_BRES_4_receipts_unchanged (payment and settlement replays after a batch) |
| R4-BRES.5 **H** | Batch | "New statements reflect the new revisions; earlier snapshot tokens continue to page their frozen entries." | behaviour | test_R4_BRES_5_statements_and_snapshots |
| R4-BRES.6 **H** | Batch | "Replays return the original batch response with 200." | behaviour | test_R4_BRES_6_replay_original_batch_response (after newer revisions) |
| R4-BRES.7 **H** | derived, D-68 | a revision from a batch carries the item's `effective_at` (verbatim), `reason`, new `amount`, `revision` = previous + 1 | format | test_R4_BRES_1_shape_and_order |

### Settlements under stage 4 (SET)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-SET.1 **H** | Batch | "A settlement payment may be refunded under the existing refund rules, but refunds never change settlement membership." | behaviour | test_R4_SET_1_member_refund_keeps_membership (refund has settlement_id null; the batch still needs exactly the original members) |
| R4-SET.2 **H** | Batch | "Existing receipts and saved statements must remain available in their original form." | invariant | test_R4_BRES_4_receipts_unchanged; test_R4_BRES_5_statements_and_snapshots |

### Concurrency and atomicity (CONC)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-CONC.1 **H** | Batch | "Concurrent corrections sharing any expected payment revision cannot both succeed." | invariant | test_R4_CONC_1_single_vs_batch_vs_batch_race (20 parallel: singles and batches overlapping on one payment → exactly one 201) (D-70) |
| R4-CONC.2 **H** | task note | changes to many records are all-or-none under concurrent writes | invariant | test_R4_CONC_2_batch_atomic_under_load (readers never see a partial batch: either all or none of the new revisions; Σ totals constant) |
| R4-CONC.3 **H** | Batch | failure injected mid-batch (a late item or the historical check fails) changes nothing | invariant | test_R4_CONC_3_failure_last_item_and_historical_changes_nothing |

### Upgrades and snapshots (UPG)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R4-UPG.1 **H** | Batch | "A stage-4 service must accept exports produced by the same team's stages 1–3, retaining settlement membership, corrections and snapshots." | behaviour | test_R4_UPG_1_populated_stage1_2_3_exports (memberships, revisions, recorded times, receipts, tokens) |
| R4-UPG.2 **H** | L10, L12 | stage-4 exports carry snapshot tokens with their frozen results; importing merges them into the store (destination tokens keep paging) | behaviour | test_R4_UPG_2_stage4_snapshots_round_trip (token pages identically after export → reset → import) (D-74) |
| R4-UPG.3 **H** | L10 | frozen stage-3 exports contain no snapshots; stage-3 tokens cannot survive the upgrade (known limitation) | operational | untestable: limitation recorded (D-74); the suite asserts only that importing a stage-3 export succeeds |
| R4-UPG.4 **H** | derived, D-72 | imported payments get `refund_of: null`; stored receipts replay verbatim | behaviour | test_R4_UPG_4_old_receipts_replay_verbatim |
| R4-UPG.5 **H** | derived, D-74 | imported settlements can be batch-corrected (membership kept), imported captures stay immutable | behaviour | test_R4_UPG_5_imported_settlement_batch_correctable |

## Part B — earlier rows changed by stage 4

| id | earlier rule (short) | changed by | new rule |
|---|---|---|---|
| R-7.1 / R2-HOLD.16 / R3-COR.14 | eight idempotent paths | R4-PATH.1 | ten: + refunds, correction batches |
| R-8.5 / R2-CAP.6 (payment key set) | 13 keys | R4-RSH.5 | + `refund_of` (null except refunds) on every payment object |
| R3-SET.3 / R3-COR.15 / D-46 / D-59 | members immutable to single corrections | R4-RCOR.5, R4-BAT.1 | still immutable on the single path; correctable via batches (all members) |
| R3-COR.15 / D-46 | single-correction precedence | R4-RCOR.4 | + 422 linked for refunds; + 422 refund_exceeds_payment after stale |
| R3-MNY.3 | correction debit vs current available | R4-RCOR.3 | unchanged rule, now also floors at refunded amount (R4-RCOR.2) |
| R3-REV / R3-RVL.5 / D-47 | revision item shape | R4-BRES.3 | + `correction_batch_id` (null unless from a batch) |
| R3-SNAP.6 / D-50 / L8 | snapshots in process, not exported | R4-UPG.2, L10 | stage-4 exports carry snapshots; import restores them |
| R3-UPG.* / D-52 | upgrade from stages 1–2 | R4-UPG.1 | stage 4 accepts stage 1, 2 and 3 exports |
| R3-COR.16 / D-60 | same-expected race among single corrections | R4-CONC.1 | across single corrections and batches |

## Coverage table

| area | rows | example/edge tests | property tests | untestable | hidden (H) |
|---|---|---|---|---|---|
| PATH | 3 | 3 | 0 | 0 | 3 |
| REF | 10 | 10 | 0 | 0 | 7 |
| RSH | 8 | 8 | 0 | 0 | 6 |
| RCOR | 5 | 5 | 0 | 0 | 4 |
| BAT | 13 | 13 | 0 | 0 | 8 |
| BERR | 3 | 3 | 0 | 0 | 3 |
| BMNY | 5 | 4 | 1 | 0 | 5 |
| BRES | 7 | 7 | 0 | 0 | 6 |
| SET | 2 | 2 | 0 | 0 | 2 |
| CONC | 3 | 3 | 0 | 0 | 3 |
| UPG | 5 | 4 | 0 | 1 | 5 |
| **Total** | **64** | **62** | **1** | **1** | **52** |

Untestable: R4-UPG.3 (a recorded limitation: frozen stage-3 exports carry no snapshots). Recompute
with `grep -c '^| R4-' ledger.md`.

## Risk list — the five most likely to be built wrong

1. **R4-BERR.1/3, R4-BAT.9/10/13 batch precedence.** Item errors strictly in input order (with a
   fixed in-item order), then settlement completeness (and member instant identity), then combined
   current available, then historical — a batch with several faults must report the first one in
   that order, never the "most severe".
2. **R4-BMNY.1–4, R4-CONC.2/3 atomic combined effect.** Affordability and history must be judged on
   all proposed revisions together (net per wallet, every boundary incl. holds), and any failure —
   even on the last item or in the historical pass — must leave balances, revisions, statements,
   snapshots and keys untouched; readers under load must never see half a batch.
3. **R4-REF.7/8, R4-RCOR.2 refund caps.** Cumulative refunds against the *current corrected* amount;
   corrections floored at the refunded total (single and batch); refunds from *available* (held funds
   excluded); refunds of refunds 422 `invalid_refund_target`, refunds immutable to corrections.
4. **R4-CONC.1 cross-path races.** A single correction and a batch (or two batches) that share an
   expected revision on any payment: exactly one succeeds, the rest 409 `stale_revision`.
5. **R4-UPG.1/2, L10 upgrades.** Stage 1–3 exports with memberships, revisions and receipts; stage-4
   exports carrying snapshots and restoring them; `refund_of` added on read without rewriting stored
   receipts.
