# Stage 3 requirements ledger — Pocketful: statements and payment corrections

Sources of truth: `runlog/stage3-spec.md` (stage 3), `runlog/stage2-spec.md`, `runlog/stage1-spec.md`
("The requirements from stages 1 and 2 continue to apply, with the additions below"). Stage 1's
228 rows (`stage-1/docs/ledger.md`, frozen 9d7ab5e) and stage 2's 182 rows (`stage-2/docs/ledger.md`,
frozen 6a3fd33) stay in force; rows stage 3 changes are listed in **Part B**. Part A holds the new
rows. Time semantics are fixed by the decision records D-41…D-60 (`docs/decisions/`), cited as `D-nn`.

- **id**: `R3-<area>.<n>`, stable once published. Areas: TS payment timestamps and seeding, ME
  `GET /me` temporal reads, ST `GET /statement`, REV revision model, COR correction endpoint
  (validation, response, idempotency), MNY money movement and overdraft rules of corrections, RVL
  `GET /payments/{id}/revisions`, KN `known_at` selection, SNAP stable statement pagination, SET
  settlement/capture links, UPG upgrades over populated state, HH historical holds, INV invariants
  across every historical view.
- **kind**: behaviour, error, invariant, limit, format, operational.
- **proof**: planned test in `stage-3/acceptance/stage3/` (`test_R3_<AREA>_<n>_...`), all over
  HTTP; `prop:` = property/differential test (a reference model in the test computes the expected
  value from the spec's rules and is compared with the service across many generated instants);
  `untestable: <reason>`.
- **H** = hidden: unlikely to be probed by a quick reading or the event's small shipped subset.

Notation used in quotes and decisions: *T* = `as_of`, *K* = `known_at`, *E(p)* / *R(p)* = selected
effective / recorded instant of payment *p*, *now* = the read instant (D-43).

## Part A — new stage 3 requirements

### Payment timestamps and seeding (TS)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-TS.1 | Timestamps | "Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it moved money." | format | test_R3_TS_1_created_at_rfc3339_every_payment_kind (direct, request pay, settlement member, capture, seeded, imported) |
| R3-TS.2 | Timestamps | "Every endpoint returning a payment includes it." | format | test_R3_TS_2_created_at_on_every_payment_surface (POST /payments, pay, capture, settlements, /activity, /statement entries) |
| R3-TS.3 | Timestamps | "`GET /activity` retains its existing ordering by this field." | behaviour | test_R3_TS_3_activity_order_by_created_at_incl_seeded_past (seeded created_at in the past sorts below newer API payments) |
| R3-TS.4 **H** | Timestamps | "Seeded payments may supply `created_at`" | behaviour | test_R3_TS_4_seeded_created_at_kept (echoed by instant on /activity, revisions, statement) |
| R3-TS.5 **H** | Timestamps | "omission uses reset time, before subsequent API-created payments." | behaviour | test_R3_TS_5_omitted_created_at_is_reset_time_before_api_payments (seeded without created_at sorts before an API payment made immediately after reset, in /activity and /statement) (D-44) |
| R3-TS.6 **H** | Timestamps | "A seeded `created_at` in the future gives `422 validation_failed` from `POST /_test/reset`, with no state change." | error | test_R3_TS_6_seeded_future_created_at_422_state_unchanged (now+5 s → 422; old token, balances, feed intact; created_at = now−1 s accepted) |
| R3-TS.7 **H** | Timestamps | "A fixture's `balance` remains the balance after all seeded payments. Loading those payments must not change that balance." | behaviour | test_R3_TS_7_seeded_balance_is_ending_balance (/me current = fixture balance with dated seeded payments) |
| R3-TS.8 **H** | Effective time | "A seeded payment's supplied `created_at` is also its original recorded/effective time; omission uses reset time." | behaviour | test_R3_TS_8_seeded_revision1_times (revisions[0].effective_at = recorded_at = created_at) |
| R3-TS.9 **H** | Effective time | "Seeded history is consistent and nonnegative." | invariant | test_R3_TS_9_inconsistent_seeded_history_422 (opening balance would be negative, or a seeded boundary negative → 422) (D-45) |
| R3-TS.10 **H** | derived, D-41 | server-assigned instants have microsecond precision and are strictly increasing across the service (monotonic) | format | test_R3_TS_10_server_instants_strictly_increase (50 rapid payments: created_at strictly increasing; tie-free) |
| R3-TS.11 **H** | derived, D-44 | ties among equal `created_at` (seeded or settlement members) order by payment id ascending (code-point order) | behaviour | test_R3_TS_11_equal_created_at_tiebreak_by_id (statement and as_of boundaries) |

### `GET /me` as of an instant (ME)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-ME.1 | GET /me | "`as_of` is optional and is an RFC 3339 instant with an offset." | behaviour | test_R3_ME_1_as_of_accepts_offsets (`Z`, `+02:00`, `-05:30`, fractional seconds; same instant → same answer) (D-42) |
| R3-ME.2 **H** | GET /me | "Anything else — a naive local time, a bare date, an empty value — is 422 `validation_failed`." | error | test_R3_ME_2_as_of_invalid_422 (`2026-09-24T13:20:00`, `2026-09-24`, ``, `now`, `1727184000`, `2026-13-01T00:00:00Z`, `2026-09-24 13:20:00Z`) |
| R3-ME.3 **H** | GET /me | "Without temporal query parameters the response retains the existing money fields and reports current corrected values." | behaviour | test_R3_ME_3_no_params_shape_unchanged_and_corrected (exact stage-2 key set; balance reflects corrections) |
| R3-ME.4 **H** | GET /me | "`balance` is the caller's balance as it stood at that instant: the balance after every payment of theirs with `created_at` at or before `as_of`, and before every payment after it." | behaviour | prop: test_R3_ME_4_as_of_matches_reference_model (every boundary ±1 µs) |
| R3-ME.5 **H** | GET /me | "A payment made at exactly `as_of` counts as having happened." | behaviour | test_R3_ME_5_as_of_inclusive_at_exact_instant (as_of = created_at string, and the same instant in another offset) |
| R3-ME.6 | GET /me | "An `as_of` at or after the latest payment returns the current balance." | behaviour | test_R3_ME_6_as_of_after_latest_is_current (and far future) |
| R3-ME.7 **H** | GET /me | "An `as_of` before the earliest payment returns the opening balance — what the wallet held before anything moved." | behaviour | test_R3_ME_7_as_of_before_earliest_is_opening (seeded: balance − net of seeded; signup user: 0) |
| R3-ME.8 **H** | GET /me | "The response carries `as_of` back, exactly as given." | format | test_R3_ME_8_as_of_echoed_verbatim (offset, fraction and case preserved; absent when not supplied) (D-43) |
| R3-ME.9 **H** | Historical holds | "For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view: `balance = total`, `available = total - held`." | invariant | prop: test_R3_ME_9_four_fields_same_view |
| R3-ME.10 **H** | KN | "Echo supplied `known_at` exactly." | format | test_R3_ME_10_known_at_echoed_verbatim |

### `GET /statement` (ST)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-ST.1 | Statement | "Both `from` and `to` are optional; `from` defaults to the opening of the wallet and `to` to now." | behaviour | test_R3_ST_1_defaults_full_history_to_now (D-43) |
| R3-ST.2 | Statement | "`limit` and `offset` behave exactly as in `GET /requests`." | limit | test_R3_ST_2_limit_offset_rules (1..200, default 50, plain digits, huge offset valid, has_more) |
| R3-ST.3 | Statement | "Returns the payments the caller sent or received in the half-open window `[from, to)`, **oldest first**, each with the caller's balance immediately after it" | behaviour | test_R3_ST_3_half_open_window (payment at exactly `from` included, at exactly `to` excluded) |
| R3-ST.4 | Statement | response `{ "opening_balance", "entries": [ { "payment", "delta", "balance_after" } ], "closing_balance", "has_more" }` (+ revision fields and `snapshot`) | format | test_R3_ST_4_shape (D-49) |
| R3-ST.5 | Statement | "Entries are ordered by `created_at` ascending, then payment `id` ascending for ties." (stage 3 final: by selected `effective_at`, then id — R3-KN.6) | behaviour | test_R3_ST_5_order_effective_then_id |
| R3-ST.6 **H** | Statement | "`opening_balance` is the balance immediately before `from`. `closing_balance` is the balance immediately before `to`." | behaviour | prop: test_R3_ST_6_opening_closing_match_me_as_of (opening = /me as_of from−1µs; closing = as_of to−1µs, same K) |
| R3-ST.7 **H** | Statement | "`opening_balance` plus all `delta` values in the full window must equal `closing_balance`." | invariant | prop: test_R3_ST_7_opening_plus_deltas_equals_closing (all pages concatenated) |
| R3-ST.8 | Statement | "A sent payment has a negative `delta`; a received payment has a positive `delta`." | behaviour | test_R3_ST_8_delta_sign |
| R3-ST.9 **H** | Statement | "Pagination must not change an entry's `balance_after` or the window's opening and closing balances. These values describe the full window regardless of `limit` and `offset`." | invariant | test_R3_ST_9_pagination_does_not_change_balances (limit 1..n, every offset) |
| R3-ST.10 **H** | Statement | "Only payments sent or received by the caller appear in their statement, including when other payments are public. The activity-feed visibility rules do not apply to statements." | invariant | test_R3_ST_10_only_own_payments_public_or_private (third-party public payments absent; own private present) |
| R3-ST.11 | derived | `balance_after` of entry *i* = opening_balance + Σ deltas of entries 0..i in window order | invariant | prop: test_R3_ST_11_running_balance |
| R3-ST.12 **H** | derived, D-54 | `from`/`to` invalid instants → 422; `from` > `to` → 422; `from` = `to` → empty window, opening = closing | error | test_R3_ST_12_window_validation |
| R3-ST.13 | Statement | "This abbreviated example omits the revision fields and `snapshot` token described below." | format | test_R3_ST_4_shape |
| R3-ST.14 **H** | derived, D-49 | settlement members appear as separate entries sharing one instant (combined boundary), captures appear once | behaviour | test_R3_ST_14_settlement_members_and_captures_in_statement |

### Revision model (REV)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-REV.1 **H** | Effective time | "The service must distinguish **when money took effect** from **when it learned that fact**." | behaviour | prop: test_R3_KN_matrix (as_of × known_at grid against the model) |
| R3-REV.2 | Effective time | "Every payment has a revision history." | behaviour | test_R3_REV_2_every_payment_kind_has_revision_1 |
| R3-REV.3 **H** | Effective time | "Revision 1 has `amount` as originally paid and `effective_at = recorded_at = created_at`." | format | test_R3_REV_3_revision1_fields (direct, request pay, member, capture, seeded, imported) (D-47) |
| R3-REV.4 **H** | Effective time | "Opening balances equal seeded ending balances minus the net effect of original seeded payments." | behaviour | test_R3_ME_7_as_of_before_earliest_is_opening |
| R3-REV.5 **H** | Effective time | "Corrections must not change those opening balances." | invariant | test_R3_REV_5_corrections_keep_opening (correct a seeded payment, also to 0 and to an earlier effective_at: as_of before everything unchanged) |
| R3-REV.6 | Effective time | "New accounts open at zero." | behaviour | test_R3_REV_6_signup_opens_at_zero |
| R3-REV.7 **H** | Corrections | "It appends an immutable revision" | invariant | test_R3_REV_7_revisions_immutable (list unchanged after later revisions except appended ones) |
| R3-REV.8 **H** | Corrections | "Recorded times for one payment strictly increase." | invariant | test_R3_REV_8_recorded_at_strictly_increases (3 corrections inside one second) (D-41) |
| R3-REV.9 **H** | Corrections | "Correction changes neither parties nor visibility." | invariant | test_R3_REV_9_parties_visibility_unchanged (statement payment object, /activity, feed visibility for third parties) |

### Correction endpoint (COR)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-COR.1 | Corrections | "`POST /payments/{payment_id}/corrections` requires an idempotency key and the original sender." | behaviour | test_R3_COR_1_requires_key_400 |
| R3-COR.2 | Corrections | "An authenticated non-sender gets 403 `forbidden`" | error | test_R3_COR_2_receiver_and_third_party_403 |
| R3-COR.3 | Corrections | "unknown payment gets 404." | error | test_R3_COR_3_unknown_payment_404 |
| R3-COR.4 | Corrections | body `{"expected_revision", "amount", "effective_at", "reason"}` — "All fields are required." | error | test_R3_COR_4_each_field_missing_422 |
| R3-COR.5 **H** | Corrections | "Revision is a positive integer" | error | test_R3_COR_5_expected_revision_rules (0, −1, 1.5, "1", true, null → 422; 1.0 accepted) (D-46) |
| R3-COR.6 **H** | Corrections | "amount is an integer 0..1000000000 (zero reverses the entire payment)" | error | test_R3_COR_6_amount_rules (−1, 1e9+1, 2.5, "5", true, null → 422; 0 and 1e9 accepted) |
| R3-COR.7 **H** | Corrections | "reason is a string of 1..200 characters" | error | test_R3_COR_7_reason_rules ("" and 201 chars → 422; 1 and 200 chars, emoji counted as one code point, accepted; non-string → 422) |
| R3-COR.8 **H** | Corrections | "effective time is an RFC 3339 instant not later than now." | error | test_R3_COR_8_effective_at_rules (naive, date, future by 2 s → 422; exactly server-now-ish and past accepted) |
| R3-COR.9 **H** | Corrections | "Invalid input is 422 `validation_failed`." | error | test_R3_COR_9_wrong_types_are_422_not_400 (D-46) |
| R3-COR.10 | Corrections | "returning 201 with `payment_id`, `revision`, `amount`, `effective_at`, server-assigned `recorded_at`, and `reason`." | format | test_R3_COR_10_response_shape (exact key set; revision = previous+1) |
| R3-COR.11 | Corrections | "A stale expected revision gives 409 `stale_revision`." | error | test_R3_COR_11_stale_revision_409 (lower and higher than current) |
| R3-COR.12 **H** | Corrections | "Successful replay returns that original revision with 200 even after newer revisions." | behaviour | test_R3_COR_12_replay_after_newer_revisions_200_original |
| R3-COR.13 | Corrections | "Different body with the same key is 409 `idempotency_key_reuse`." | error | test_R3_COR_13_reuse_409 |
| R3-COR.14 **H** | §7 carried | claimed key resolved before validation; failed 4xx (stale, overdraft, insufficient) leaves the key reusable; key scoped per user + path; 20 concurrent identical → one 201 | behaviour | test_R3_COR_14_idempotency_rules (eighth idempotent path) |
| R3-COR.15 **H** | derived, D-46 | precedence: 401 → 400 body → 400/422 key → replay/reuse → 422 fields → 404 → 403 → 422 linked → 409 stale → 409 insufficient → 409 historical_overdraft | error | test_R3_COR_15_precedence_pairs |
| R3-COR.16 **H** | Stable pagination | "Concurrent corrections using the same expected revision cannot both succeed." | invariant | test_R3_COR_16_concurrent_same_expected_one_wins (20 distinct keys → one 201, rest 409 stale_revision; money moved once) |

### Money movement and overdraft (MNY)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-MNY.1 **H** | Corrections | "The difference from the previous amount moves between the **same two wallets** in the same atomic step." | behaviour | test_R3_MNY_1_delta_moves_between_same_wallets (third parties untouched) |
| R3-MNY.2 **H** | Corrections | "Increasing the amount debits the original sender; decreasing it debits the original receiver." | behaviour | test_R3_MNY_2_increase_debits_sender_decrease_debits_receiver |
| R3-MNY.3 **H** | Corrections | "A currently unaffordable debit gives 409 `insufficient_funds`." | error | test_R3_MNY_3_current_unaffordable_409 (against current available, incl. held funds) |
| R3-MNY.4 **H** | Corrections | "Otherwise, if any user's corrected balance is negative at any effective-time boundary, return 409 `historical_overdraft`." | error | test_R3_MNY_4_historical_overdraft_409 (receiver spent the money before the correction's effective time; sender's earlier balance) |
| R3-MNY.5 **H** | Corrections | "Balances at a boundary include the combined effect of all movements at that instant." | behaviour | test_R3_MNY_5_boundary_combines_same_instant (settlement member pair at one instant: no false overdraft) |
| R3-MNY.6 **H** | Corrections | "Either failure preserves balances, revision history, statements and idempotency state." | invariant | test_R3_MNY_6_failures_change_nothing (balances, revisions, statement, key reusable) |
| R3-MNY.7 **H** | Corrections | "The sum of balances must equal the seeded total in every historical view." | invariant | prop: test_R3_INV_1_sum_conserved_every_view |
| R3-MNY.8 **H** | Historical holds | "A correction is rejected with 409 `historical_overdraft` if it makes either total or available negative at any past effective/event boundary, under the latest known revisions." | error | test_R3_MNY_8_overdraft_on_available_via_hold (a hold active at the effective time) |
| R3-MNY.9 **H** | Historical holds | "Current unaffordable debits still take precedence as `insufficient_funds`." | error | test_R3_MNY_9_insufficient_precedes_historical |
| R3-MNY.10 **H** | Corrections | zero amount "reverses the entire payment" | behaviour | test_R3_MNY_10_zero_reverses (both wallets back to pre-payment balances; statement entry delta 0) |
| R3-MNY.11 **H** | derived, D-46 | a correction with the same amount (delta 0) and another effective time is allowed, moves no money now, shifts history | behaviour | test_R3_MNY_11_same_amount_moves_only_history |
| R3-MNY.12 **H** | derived, D-46 | request-pay payments, seeded payments and imported payments are correctable (only settlement members and captures are linked) | behaviour | test_R3_MNY_12_correct_request_pay_seeded_imported |

### Revisions endpoint (RVL)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-RVL.1 | Revisions | "`GET /payments/{payment_id}/revisions` returns `{"revisions": [...]}` in revision order, including revision 1 (`reason: ""`)." | format | test_R3_RVL_1_list_in_order_with_revision1 |
| R3-RVL.2 **H** | Revisions | "Only the two parties can read it; a third party gets 404 even for a public payment." | error | test_R3_RVL_2_third_party_404_public_and_private (operator too) |
| R3-RVL.3 | Revisions | "No token is 401." | error | test_R3_RVL_3_no_token_401 |
| R3-RVL.4 | derived | unknown payment → 404 | error | test_R3_RVL_4_unknown_404 |
| R3-RVL.5 **H** | derived, D-47 | each revision item has the correction response's shape (`payment_id, revision, amount, effective_at, recorded_at, reason`) | format | test_R3_RVL_5_item_shape_matches_correction_response |

### `known_at` selection (KN)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-KN.1 | KN | "`GET /me` and `GET /statement` accept optional `known_at`, an RFC 3339 instant with offset." | behaviour | test_R3_KN_1_accepted_on_me_and_statement |
| R3-KN.2 **H** | KN | "For each payment, select its latest revision recorded **at or before** `known_at`; if none was yet recorded, that payment contributes nothing." | behaviour | prop: test_R3_KN_matrix |
| R3-KN.3 **H** | KN | "Omission means everything known when the read begins." | behaviour | test_R3_KN_3_omitted_is_all_known (D-43) |
| R3-KN.4 **H** | KN | "Then apply selected revisions according to their **effective** times. `as_of` retains its inclusive meaning; a statement retains its half-open window." | behaviour | prop: test_R3_KN_matrix (boundary cases at exactly effective_at / recorded_at) |
| R3-KN.5 **H** | KN | "Both query instants may be in the future. Invalid/empty instants are 422." | behaviour | test_R3_KN_5_future_allowed_invalid_422 |
| R3-KN.6 **H** | KN | "Statement ordering is now by selected `effective_at`, then payment id." | behaviour | test_R3_KN_6_order_follows_selected_effective (a backdated correction moves an entry earlier) |
| R3-KN.7 **H** | KN | "Each entry retains `payment`, `delta` and `balance_after`, and adds the selected `revision`, `effective_at` and `recorded_at`." | format | test_R3_KN_7_entry_fields |
| R3-KN.8 **H** | KN | "`payment.amount` is the selected amount for this statement." | behaviour | test_R3_KN_8_payment_amount_is_selected (and /activity still shows the original) |
| R3-KN.9 **H** | KN | "Zero-amount revisions still appear as entries with zero delta." | behaviour | test_R3_MNY_10_zero_reverses |
| R3-KN.10 **H** | KN | "No correction is counted alongside the revision it replaces." | invariant | test_R3_KN_10_one_entry_per_payment (never two entries for one payment) |
| R3-KN.11 **H** | KN | "With no corrections and no `known_at`, previous behavior is unchanged." | behaviour | test_R3_KN_11_no_corrections_previous_behaviour |
| R3-KN.12 **H** | KN | (derived) a correction moves a payment into or out of a window by its selected effective time — "A correction may move a payment into or out of a statement window." | behaviour | test_R3_KN_12_correction_moves_entry_across_window |

### Stable statement pagination (SNAP)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-SNAP.1 | Snapshot | "Every first `GET /statement` response additionally returns an opaque `snapshot` token." | format | test_R3_SNAP_1_token_returned (opaque non-empty string; D-50) |
| R3-SNAP.2 **H** | Snapshot | "It freezes the caller's selected revisions, window, balances, entries and default `to` at that read." | invariant | test_R3_SNAP_2_frozen_after_payment_correction_capture (pages identical to the first read after new payments, corrections and hold events) |
| R3-SNAP.3 **H** | Snapshot | "`GET /statement?snapshot=<token>&limit=...&offset=...` pages that exact result, even after payments or corrections." | behaviour | test_R3_SNAP_2_frozen_after_payment_correction_capture |
| R3-SNAP.4 **H** | Snapshot | "Only limit and offset may accompany a snapshot; supplying `from`, `to` or `known_at` with it gives 422 `validation_failed`." | error | test_R3_SNAP_4_snapshot_with_window_params_422 (each, incl. empty values) |
| R3-SNAP.5 **H** | Snapshot | "Unknown token, another user's token, or a token from before reset gives 404 `not_found`." | error | test_R3_SNAP_5_unknown_other_user_pre_reset_404 |
| R3-SNAP.6 | Snapshot | "Tokens last until reset. No storage survival across container restarts is required." | behaviour | test_R3_SNAP_6_token_valid_until_reset (D-50 import rule) |
| R3-SNAP.7 **H** | Snapshot | "Paging changes neither balances nor entries; the final partial page and offsets beyond the end must report `has_more` correctly." | behaviour | test_R3_SNAP_7_paging_has_more_and_beyond_end |
| R3-SNAP.8 | Snapshot | "Unrecognized query parameters remain ignored under stage 1's general rule." | behaviour | test_R3_SNAP_8_unknown_params_ignored_with_snapshot |
| R3-SNAP.9 **H** | Snapshot | "Existing snapshots remain unchanged during concurrent payments or corrections." | invariant | test_R3_SNAP_9_concurrent_writes_while_paging |
| R3-SNAP.10 **H** | Historical holds | "Old snapshots remain unchanged after any lifecycle action or correction." | invariant | test_R3_SNAP_2_frozen_after_payment_correction_capture |
| R3-SNAP.11 **H** | derived, D-50 | limit/offset with a snapshot follow the GET /requests rules (422); every non-snapshot read mints a new token | error | test_R3_SNAP_11_snapshot_paging_validation |

### Settlement and capture links (SET)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-SET.1 | Settlement | "Stage-1 settlements retain their original receipts and privacy rules." | behaviour | test_R3_SET_1_settlement_receipts_unchanged (replay 200 identical; feed visibility) |
| R3-SET.2 **H** | Settlement | "Each member's original revision uses its shared committed_at as both effective_at and recorded_at." | format | test_R3_SET_2_member_revision1_committed_at |
| R3-SET.3 **H** | Settlement | "Single-payment corrections reject settlement members with 422 `linked_payment_immutable`." | error | test_R3_SET_3_member_correction_422_linked (even by the member's sender, valid body) |
| R3-SET.4 **H** | Settlement | "Captures are immutable linked payments: a correction of a capture gives 422 `linked_payment_immutable`." | error | test_R3_SET_4_capture_correction_422_linked |
| R3-SET.5 **H** | Historical holds | "Captures appear exactly once with their links." | behaviour | test_R3_ST_14_settlement_members_and_captures_in_statement (authorization_id present) |
| R3-SET.6 **H** | Historical holds | "`GET /statement` still contains money movements only: authorization, release and expiry are not payments." | behaviour | test_R3_SET_6_holds_not_in_statement |

### Upgrades over populated state (UPG)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-UPG.1 **H** | Settlement | "A stage-3 service must accept exports produced by the same team's stage-1 or stage-2 service." | behaviour | test_R3_UPG_1_populated_stage1_and_stage2_exports_import (real exports from the frozen images: payments, requests, splits, settlements, receipts; stage 2 adds holds and captures) |
| R3-UPG.2 **H** | Settlement | "The ledger must import and account for authorizations and captures." | behaviour | test_R3_UPG_2_imported_holds_and_captures_accounted (/me current and as_of; statements include captures; held matches) |
| R3-UPG.3 **H** | derived, D-52 | every imported payment has revision 1 with effective = recorded = created_at (members: committed_at); opening balances derived as current − net of all imported payments | behaviour | test_R3_UPG_3_imported_revision1_and_opening |
| R3-UPG.4 **H** | derived, D-52 | imported receipts (all seven older paths) replay 200; tokens survive; imported pending requests payable; imported payments correctable unless linked | behaviour | test_R3_UPG_4_receipts_tokens_requests_corrections_after_import |
| R3-UPG.5 **H** | derived, D-52 | a stage-3 export round-trips into stage 3 with revisions, recorded times, snapshots and closed_at preserved | behaviour | test_R3_UPG_5_stage3_round_trip |
| R3-UPG.6 **H** | derived, D-52 + L5 | importing a stage-1 or stage-2 export keeps destination sessions whose user id, email and handle match; a stage-3 export is pure replacement | behaviour | test_R3_UPG_6_session_rule_by_source_stage |

### Historical holds (HH)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-HH.1 **H** | Historical holds | "A hold starts at authorization creation" | behaviour | prop: test_R3_HH_model (held at created_at inclusive) |
| R3-HH.2 **H** | Historical holds | "nonfinal capture reduces it at capture time" | behaviour | test_R3_HH_2_nonfinal_capture_reduces_at_capture_time |
| R3-HH.3 **H** | Historical holds | "final capture, void or expiry releases the remainder at that event's time." | behaviour | test_R3_HH_3_release_at_event_time (final capture, void, expiry) |
| R3-HH.4 **H** | Historical holds | "Expiry takes effect at `expires_at`." | behaviour | test_R3_HH_4_expiry_at_expires_at_even_without_request (as_of = expires_at → released; −1 µs → held) |
| R3-HH.5 **H** | Historical holds | "Events other than clock expiry are known at their server-assigned event time." | behaviour | test_R3_HH_5_known_at_hides_later_events (known_at before a void: hold still active at as_of after the void) |
| R3-HH.6 **H** | Historical holds | "Once creation is known, the expiry deadline is known too." | behaviour | test_R3_HH_6_expiry_known_with_creation (known_at = creation, as_of after deadline → released) |
| R3-HH.7 **H** | Historical holds | "For queries beyond now, an open hold expires at its deadline." | behaviour | test_R3_HH_7_future_as_of_releases_at_deadline |
| R3-HH.8 **H** | Historical holds | "Without `as_of`, use the instant the request began." | behaviour | test_R3_HH_8_known_at_only_uses_read_instant |
| R3-HH.9 **H** | Historical holds | "Authorizations expose `closed_at` (null while open; event time when closed)." | format | test_R3_HH_9_closed_at (open null; captured = final capture time; voided = void time; expired = expires_at) (D-51) |
| R3-HH.10 **H** | Historical holds | "Historical `total` follows stage-3 effective/recorded-time rules." | behaviour | prop: test_R3_HH_model |
| R3-HH.11 **H** | Historical holds | "Seeded open holds are assumed created at reset unless `created_at` is supplied; seeded closed holds need not reconstruct a prior lifecycle." | behaviour | test_R3_HH_11_seeded_holds_history (D-51) |
| R3-HH.12 **H** | derived, D-51 | a hold whose creation is not yet known at K contributes nothing; held never counts a hold before its created_at | behaviour | prop: test_R3_HH_model |

### Invariants across views (INV)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R3-INV.1 **H** | Corrections | "The sum of balances must equal the seeded total in every historical view." | invariant | prop: test_R3_INV_1_sum_conserved_every_view (every user's /me at every boundary ±1 µs × several known_at, after corrections incl. backdated and zero) |
| R3-INV.2 **H** | stage 2 carried | `available = total − held ≥ 0` and `total ≥ 0` in every historical view (all corrections accepted only if they keep this) | invariant | prop: test_R3_INV_2_nonnegative_every_view |
| R3-INV.3 **H** | derived | current `GET /me` balance equals `GET /me?as_of=<far future>` and the closing balance of an unbounded statement | invariant | test_R3_INV_3_current_equals_views |
| R3-INV.4 **H** | stage 2 carried, "Concurrent operations" | concurrent payments, corrections, captures and statement reads behave as some serial order; snapshots unaffected | invariant | test_R3_INV_4_concurrent_mixed_serialisable |

## Part B — stage 1 / stage 2 rows changed by stage 3

| id | earlier rule (short) | changed by | new rule |
|---|---|---|---|
| R-3.9 / D-16 | timestamps RFC 3339, server emits whole seconds | R3-TS.10, D-41 | server-assigned instants carry microseconds, strictly increasing; still RFC 3339 with offset |
| R-3.5 / R-4.29 / R2-MOD.1 | fixture shape | R3-TS.4–9, R3-HH.11 | payments may carry `created_at` (future → 422); seeded history must be consistent; authorizations may carry `created_at` |
| R-4.27 | negative fixture balance → 422 | R3-TS.6, R3-TS.9 | also future `created_at` and negative seeded history → 422, nothing changes |
| R-7.1 / R2-HOLD.16 | seven idempotent paths | R3-COR.1/14 | eight: + `POST /payments/{id}/corrections` |
| R-8.1 / R2-ME.1 | `GET /me` shape | R3-ME.*, R3-KN.* | optional `as_of`/`known_at`; shape unchanged without them; echoes when supplied |
| R-8.62 / R2-FEED | feed items are original payments | R3-KN.8, R3-REV.9 | still the original payment and amount; corrections are not feed items |
| R-1.6 / R2-HOLD.5 | sum of totals = seeded total | R3-INV.1 | in every historical view |
| R-1.7 / R2-HOLD.6 | total, available ≥ 0 | R3-INV.2, R3-MNY.4/8 | in every historical view; corrections rejected otherwise |
| R-5.1 table | error codes | R3-COR.11, R3-MNY.4, R3-SET.3/4 | + `stale_revision`, `historical_overdraft`, `linked_payment_immutable` |
| R-10.3/R-10.11 / R2-UPG.1/7 | import accepts own (and stage-1) exports | R3-UPG.1–5 | accepts stage-1 and stage-2 exports; preserves revisions, recorded times, snapshots |
| R-10.16 / D-22 (L5) | older-format import keeps matching sessions | R3-UPG.6 | applies to stage-1 and stage-2 exports imported into stage 3 |
| R-11.15/R-11.16 | settlement members | R3-SET.2/3 | revision 1 at committed_at; members immutable to corrections |
| R2-AUTH.3 / D-32 | authorization key set | R3-HH.9 | + `closed_at` |
| R2-CAP.4 | capture payment | R3-SET.4/5 | captures immutable to corrections; appear once in statements |
| R-8.42 / R-8.61 | list ordering | R3-TS.3 | unchanged: /activity by created_at; statements by selected effective_at then id |

## Coverage table

| area | rows | example/edge tests | property tests | untestable | hidden (H) |
|---|---|---|---|---|---|
| TS | 11 | 11 | 0 | 0 | 8 |
| ME | 10 | 8 | 2 | 0 | 8 |
| ST | 14 | 11 | 3 | 0 | 6 |
| REV | 9 | 8 | 1 | 0 | 7 |
| COR | 16 | 16 | 0 | 0 | 9 |
| MNY | 12 | 11 | 1 | 0 | 12 |
| RVL | 5 | 5 | 0 | 0 | 2 |
| KN | 12 | 10 | 2 | 0 | 11 |
| SNAP | 11 | 11 | 0 | 0 | 8 |
| SET | 6 | 6 | 0 | 0 | 5 |
| UPG | 6 | 6 | 0 | 0 | 6 |
| HH | 12 | 9 | 3 | 0 | 12 |
| INV | 4 | 2 | 2 | 0 | 4 |
| **Total** | **128** | **114** | **14** | **0** | **98** |

"Tokens last until reset. No storage survival across container restarts is required." (R3-SNAP.6) is
a permission for restarts and is not tested for restarts. Recompute: `grep -c '^| R3-' ledger.md`.

## Hidden requirements to watch

Inclusive `as_of` vs half-open `[from, to)` at the exact instant, in any offset (R3-ME.5, R3-ST.3,
R3-KN.4) · selected-revision rule "recorded at or before known_at", payment absent before its revision 1
is recorded (R3-KN.2) · opening balance = seeded ending − net of ORIGINAL seeded payments, untouched by
corrections (R3-REV.4/5) · future seeded `created_at` → 422 (R3-TS.6) · seeded omitted `created_at`
before any API payment (R3-TS.5) · recorded_at strictly increasing within one second (R3-REV.8) ·
correction wrong JSON types are 422 not 400 (R3-COR.9) · replay of a correction after newer revisions
(R3-COR.12) · `historical_overdraft` evaluated at every past boundary for total AND available, with
same-instant movements combined, after `insufficient_funds` (R3-MNY.4/5/8/9) · failures change nothing
(R3-MNY.6) · third party gets 404 (not 403) on revisions, 403 on corrections (R3-RVL.2, R3-COR.2) ·
`payment.amount` in statements is the selected amount while /activity keeps the original (R3-KN.8) ·
snapshot rejects `from`/`to`/`known_at` with 422, 404 across users and resets, frozen after every kind of
write (R3-SNAP.*) · members and captures immutable 422 (R3-SET.3/4) · populated stage-1 and stage-2
upgrades with captures, holds and receipts (R3-UPG.*) · historical holds incl. known-time of events,
expiry at deadline beyond now, `closed_at` (R3-HH.*) · Σ totals = seeded total in every (as_of, known_at)
view (R3-INV.1).

## Risk list — the five most likely to be built wrong

1. **R3-KN.2/4, R3-ME.4/5, R3-ST.3 two-time selection.** Selecting the latest revision with
   recorded_at ≤ K *per payment*, then applying it at its effective time with inclusive `as_of` and
   half-open `[from, to)`, compared by instant across offsets and at microsecond precision. Off-by-one at
   exactly the boundary and string comparison of timestamps are the classic failures.
2. **R3-MNY.4/5/8 historical_overdraft.** Must replay both parties' full corrected history (opening +
   selected movements + hold intervals) and check every past boundary with same-instant movements
   combined, for total and available, only after the current-available `insufficient_funds` check — and
   leave no trace on failure.
3. **R3-UPG.1–3 populated upgrades.** Stage-1/2 exports carry no revisions, opening balances or hold
   event times; the importer must synthesise revision 1 (members at committed_at), derive openings, link
   captures, give authorizations created/closed times that keep history nonnegative (D-52), keep receipts
   and sessions.
4. **R3-SNAP.2/9/10 snapshots.** Freezing the default `to` and `known_at` at the first read; paging must
   be immune to later payments, corrections (including backdated ones recorded later) and hold events;
   strict 422 for window params; 404 across users/reset.
5. **R3-HH.* historical holds.** Hold intervals with known-time rules (events known at event time, expiry
   known with creation, future as_of expires at deadline), seeded open holds at reset, closed_at for
   every closing path, and available/held consistent with total in every view.
