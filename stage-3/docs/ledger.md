# Stage 2 requirements ledger — Pocketful: wallet screens and payment authorizations

Sources of truth: `runlog/stage2-spec.md` (stage 2) and `runlog/stage1-spec.md` (stage 1,
"continue to apply, with the additions below"). Stage 1's 228 rows live in
`stage-1/docs/ledger.md` (frozen, accepted 9d7ab5e) and remain in force; the rows stage 2
changes are listed in **Part B** with the new rule. Part A holds the new stage 2 rows.

- **id**: `R2-<area>.<n>`, stable once published. Areas: SCR screens/routing, VIS product and
  visual quality, SIGN signup/login UI, PAY pay/request UI, AMT amount input and formatting,
  FEED activity UI, REQ requests UI, SPL split UI, SYNC refresh after actions, RACE competing
  clients / uncertain outcomes, UPG upgrade, HOLD hold invariants and API changes, MOD fixture
  model, EXP expiry, ME `GET /me`, AUTH `POST /authorizations`, CAP capture, VOID void, LIST
  `GET /authorizations`, AUI authorizations UI, CONC concurrency.
- **kind**: behaviour, error, invariant, limit, format, screen, operational.
- **proof**: planned acceptance test in `stage-2/acceptance/` (`api_*` = httpx, `ui_*` =
  playwright at 390 px and 1280 px), or `untestable: <reason>`, or `review:` (judged by the
  verifier's screen review, partly automatable).
- Committed suite (S2.A): `stage-2/acceptance/stage2/test_api_*.py` and `test_ui_*.py`; every test
  is named `test_R2_<AREA>_<n>_...` with the ids it proves, so `grep -n R2_CAP_12` finds it. The proof
  column gives the intent and planned grouping.
- **H** marks hidden requirements (unlikely to be probed by a quick reading or a sample check).
- Open readings are settled in `docs/decisions/D-21`… and cited as `D-nn`.

## Part A — new stage 2 requirements

### Screens and routing (SCR)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-SCR.1 | intro | "Users can manage payments, requests and bill splits in a browser." | screen | ui_flows.py::test_pay_request_split_end_to_end |
| R2-SCR.2 | intro | "The following screens must be reachable by URL." `/`, `/requests`, `/split`, `/signup`, `/login` (and `/authorizations`, UI section) | screen | ui_routes.py::test_required_routes_render_html[route] |
| R2-SCR.3 | intro | "Other screens must be reachable through the UI." | screen | ui_routes.py::test_navigation_reaches_every_screen |
| R2-SCR.4 | intro | "Server-side and client-side rendering are both permitted." | operational | untestable: permission |
| R2-SCR.5 **H** | intro | "The browser and the API share `/requests`. Return the UI for `Accept: text/html`; API requests without that header receive JSON." | behaviour | api_negotiation.py::test_requests_html_vs_json (Accept text/html → text/html page; no Accept / `*/*` / application/json → JSON, 401 JSON without token) (D-21) |
| R2-SCR.6 **H** | UI | "The UI and the API share `/authorizations`: serve HTML for `Accept: text/html` and JSON otherwise, as for `/requests`." | behaviour | api_negotiation.py::test_authorizations_html_vs_json |
| R2-SCR.7 | intro | "The UI must expose the `data-testid` attributes listed below for integration testing. Additional elements are permitted" | format | every ui_* test locates elements only by data-testid |
| R2-SCR.8 **H** | §2 (stage 1) carried | "Runtime assets and dependencies must be included in the image. This includes fonts, scripts and stylesheets; external services are unavailable at runtime." | operational | ui_routes.py::test_no_external_requests (playwright records every request; all same-origin) |

### Product and visual quality (VIS)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-VIS.1 | Product | "The browser experience must feel like a coherent, presentation-ready consumer finance product, not a test harness with controls attached. Aim for a calm, trustworthy character." | screen | review: verifier screen review of screenshots at 390/1280 (ui_visual.py::test_screenshots saves them) |
| R2-VIS.2 **H** | Product | "Available funds must be the clearest monetary value once holds exist, with total and held funds visibly secondary." | screen | ui_visual.py::test_available_is_headline (computed font-size/weight of wallet-available > wallet-balance and wallet-held) |
| R2-VIS.3 | Product | "Payments, requests, splits and authorisations should be easy to scan, and status, direction, privacy and money movement should be understandable without interpreting raw API data." | screen | review: + ui_visual.py::test_no_raw_json_or_enum_dump (no `{"`, no raw `u_…` ids as primary text) |
| R2-VIS.4 | Product | "Use a consistent visual system for typography, spacing, colour, controls and feedback. Primary actions must be easy to identify." | screen | review |
| R2-VIS.5 **H** | Product | "Available, held, pending, loading, successful, refused and uncertain states must be visually distinct" | screen | ui_visual.py::test_states_visually_distinct (pay-error vs pay-uncertain vs success differ in computed colour/icon; pending vs paid request items differ) |
| R2-VIS.6 | Product | "Format people, amounts and timestamps for people first; expose technical identifiers only where they help the user." | screen | review: + ui_visual.py::test_no_raw_json_or_enum_dump |
| R2-VIS.7 **H** | Product | "The required flows must remain clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling." | screen | ui_visual.py::test_no_horizontal_scroll[375,390,1280][route] (document.scrollingElement.scrollWidth ≤ innerWidth, with long notes and 1e9 amounts rendered) |
| R2-VIS.8 **H** | Product | "Inputs need visible labels" | screen | ui_a11y.py::test_every_input_has_visible_label (label[for]/aria-labelledby visible text, not placeholder-only) |
| R2-VIS.9 **H** | Product | "keyboard focus must be apparent" | screen | ui_a11y.py::test_focus_visible (Tab to each control; outline/box-shadow differs from unfocused) |
| R2-VIS.10 **H** | Product | "text and controls need sufficient contrast" | screen | ui_a11y.py::test_text_contrast_wcag_aa (computed colours, ratio ≥ 4.5 normal / 3 large & controls) |
| R2-VIS.11 **H** | Product | "Provide considered empty, loading and error states" | screen | ui_states.py::test_empty_states (empty-activity, empty-requests, empty-authorizations); ui_states.py::test_loading_state_shown_while_slow (route delay) |
| R2-VIS.12 | Product | "keep navigation consistent across the required routes" | screen | ui_routes.py::test_navigation_consistent (same nav links on every route) |
| R2-VIS.13 | Product | "A custom illustration, brand asset or exact visual match to a reference is not required." | operational | untestable: permission |

### Signup and login UI (SIGN)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-SIGN.1 | Signup | `signup-email`, `signup-password`, `signup-display-name` inputs, `signup-submit` button | screen | ui_auth.py::test_signup_flow_signs_in |
| R2-SIGN.2 | Signup | `login-email`, `login-password`, `login-submit` | screen | ui_auth.py::test_login_flow_signs_in |
| R2-SIGN.3 **H** | Signup | "`auth-error` \| Error message. Present only when there is one" | screen | ui_auth.py::test_auth_error_only_on_error (absent on load; present on wrong password, short password, email_taken, handle_taken; gone after success) |
| R2-SIGN.4 **H** | Signup | "`current-user` \| Visible on every screen when signed in. Text contains the display name" | screen | ui_auth.py::test_current_user_on_every_route |
| R2-SIGN.5 **H** | Signup | "`current-handle` \| Text is exactly the caller's handle, with no `@` and no surrounding words" | screen | ui_auth.py::test_current_handle_exact (text.strip() == handle; derived handle for signup) |
| R2-SIGN.6 | Signup | "`logout-button` \| Button" | screen | ui_auth.py::test_logout_signs_out (current-user gone; protected route shows login) |

### Balance, pay and request forms (PAY)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-PAY.1 | Balance | "`wallet-balance` \| Text is exactly the formatted amount. Carries `data-amount="{minor units}"`" (stage 2: formatted `total`) | screen | ui_wallet.py::test_wallet_balance_text_and_data_amount |
| R2-PAY.2 | Balance | `pay-handle`, `pay-amount`, `pay-note`, `pay-submit` | screen | ui_pay.py::test_pay_flow_moves_money |
| R2-PAY.3 | Balance | "`pay-visibility` \| Selects `public` or `private`. Option values are those two strings" | screen | ui_pay.py::test_pay_visibility_options_and_private |
| R2-PAY.4 | Balance | "`pay-error` \| Error message, when the payment is refused — including insufficient funds" | screen | ui_pay.py::test_pay_error_insufficient_unknown_self |
| R2-PAY.5 | Balance | `request-handle`, `request-amount`, `request-note`, `request-submit`; "`request-error` \| Error message, when the request is refused" | screen | ui_pay.py::test_request_form_creates_request_and_errors |
| R2-PAY.6 **H** | Balance | "Keep the pay form's values after success." | screen | ui_pay.py::test_form_values_kept_after_success |
| R2-PAY.7 **H** | Balance | "Submitting it again without changing a field must not send another payment: `wallet-balance` falls once, the feed contains one payment and `pay-error` is absent." | behaviour | ui_pay.py::test_resubmit_unchanged_is_replay (network log: second POST carries the same Idempotency-Key and body, answered 200) |
| R2-PAY.8 **H** | Balance | "Changing a field makes the next submission a new payment request. Retries follow §7." | behaviour | ui_pay.py::test_changed_field_new_key (new key; balance falls twice) (D-24) |

### Amount input and formatting (AMT)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-AMT.1 **H** | Balance | "`pay-amount` is a **decimal** string as a person would type it, e.g. `15.00`" | behaviour | ui_amount.py::test_decimal_inputs_submit_minor_units |
| R2-AMT.2 **H** | Formatted amount | "`wallet-balance` is the decimal with exactly `minor_units` decimal places, a single space, then the currency code: `100.00 EUR`." | format | ui_amount.py::test_formatted_amount_exact[EUR-2] (`100.00 EUR`, `0.00 EUR`, `0.05 EUR`, `1234567.89 EUR`) (D-25) |
| R2-AMT.3 **H** | Formatted amount | "For a `minor_units` of `0` there is no decimal point at all: `1200 JPY`." | format | ui_amount.py::test_formatted_amount_exact[JPY-0] |
| R2-AMT.4 **H** | Formatted amount | (derived) `minor_units: 3` → three places: `1.500 BHD`, `0.001 BHD` | format | ui_amount.py::test_formatted_amount_exact[BHD-3] |
| R2-AMT.5 | Formatted amount | "Balances are never negative, so there is no sign." | format | ui_amount.py::test_formatted_amount_exact (no "-" or "+") |
| R2-AMT.6 **H** | Formatted amount | "With `minor_units: 2`, `15.00` and `15` both submit `1500`; `15.5` submits `1550`." | behaviour | ui_amount.py::test_decimal_inputs_submit_minor_units (request body amount observed on the wire) |
| R2-AMT.7 **H** | Formatted amount | "Nonnumeric input or more than `minor_units` decimal places must show the form's error element without sending a request. For example, `15.005` is rejected rather than rounded." | behaviour | ui_amount.py::test_bad_amount_shows_error_no_request (`15.005`, `abc`, `1e3`, `15,00`, `` ; JPY `15.0`; BHD `1.0005`; zero POSTs observed) (D-23) |
| R2-AMT.8 **H** | Split / Authorize | "`split-amount` \| Decimal input, same rule as `pay-amount`"; authorize form "Same input rules as the pay form"; request form amount (D-23) | behaviour | ui_amount.py::test_same_rule_on_request_split_authorize_forms |

### Activity feed UI (FEED)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-FEED.1 | Feed | "`activity-list` \| Container. Its children are newest first in the DOM" | screen | ui_feed.py::test_activity_newest_first_dom_order (payments ≥1.1 s apart) |
| R2-FEED.2 | Feed | "`activity-item-{payment_id}` \| One per visible payment. Carries `data-visibility="public"` or `data-visibility="private"`" | screen | ui_feed.py::test_activity_items_match_api_feed (set equals GET /activity for that user, incl. seeded, captures, settlement members) |
| R2-FEED.3 | Feed | "`activity-parties-{payment_id}` \| Text contains both handles" | screen | ui_feed.py::test_activity_item_fields |
| R2-FEED.4 **H** | Feed | "`activity-amount-{payment_id}` \| Text is exactly the formatted amount" | format | ui_feed.py::test_activity_item_fields (exact text, no sign) |
| R2-FEED.5 **H** | Feed | "`activity-note-{payment_id}` \| Text is exactly the note. Present even when the note is empty" | format | ui_feed.py::test_activity_note_exact_and_empty_present (unicode/emoji/HTML-ish note rendered as text, not markup) |
| R2-FEED.6 | Feed | "`empty-activity` \| Shown instead of the list when nothing is visible" | screen | ui_states.py::test_empty_states |
| R2-FEED.7 | Feed | "Two payments with equal timestamps may appear in either order." | behaviour | untestable: permission; tests never assert intra-second order |
| R2-FEED.8 **H** | Feed + stage 1 §4 | (derived) private payments of other users never rendered; feed rule identical to `GET /activity` | invariant | ui_feed.py::test_activity_items_match_api_feed |

### Requests UI (REQ)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-REQ.1 | Requests | "`incoming-list`, `outgoing-list` \| Containers" | screen | ui_requests.py::test_incoming_outgoing_lists |
| R2-REQ.2 | Requests | "`request-item-{request_id}` \| One per request. Carries `data-status="{status}"`" | screen | ui_requests.py::test_request_items_status_all_four |
| R2-REQ.3 | Requests | "`request-amount-{request_id}` \| Text is exactly the formatted amount" | format | ui_requests.py::test_request_items_status_all_four |
| R2-REQ.4 **H** | Requests | "`request-pay-{request_id}` … `request-decline-{request_id}` \| Button. Present only on a `pending` incoming request" | screen | ui_requests.py::test_action_buttons_only_where_allowed |
| R2-REQ.5 **H** | Requests | "`request-cancel-{request_id}` \| Button. Present only on a `pending` outgoing request" | screen | ui_requests.py::test_action_buttons_only_where_allowed |
| R2-REQ.6 | Requests | "`request-error` \| Shown when a pay, decline or cancel is refused" | screen | ui_requests.py::test_pay_short_shows_request_error |
| R2-REQ.7 | Requests | "`empty-requests` \| Shown when both lists are empty" | screen | ui_states.py::test_empty_states |
| R2-REQ.8 | Requests | (derived) pay/decline/cancel buttons perform the stage 1 operations; pay uses an Idempotency-Key | behaviour | ui_requests.py::test_pay_decline_cancel_buttons (D-27 visibility default public) |

### Split UI (SPL)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-SPL.1 | Split | `split-amount`, `split-note`, `split-submit` | screen | ui_split.py::test_split_submit_creates_requests |
| R2-SPL.2 **H** | Split | "`split-handles` \| Text input: handles separated by commas, in order" | behaviour | ui_split.py::test_handles_parsed_in_order (`"ada, bob,cy"` → ["ada","bob","cy"]) (D-26) |
| R2-SPL.3 **H** | Split | "`split-preview` \| Shows the computed shares before submitting. Contains one `split-share-{handle}` per participant" | screen | ui_split.py::test_preview_before_any_post (zero POST /splits observed while preview shows) |
| R2-SPL.4 **H** | Split | "`split-share-{handle}` \| Text is exactly the formatted share amount" | format | ui_split.py::test_preview_matches_section9_table (10.00/3 → 3.34,3.33,3.33; 0.01/3 → 0.01,0.00,0.00; JPY) |
| R2-SPL.5 | Split | "`split-error` \| Error message, when the split is refused" | screen | ui_split.py::test_split_error_unknown_or_duplicate |
| R2-SPL.6 **H** | Split | "`split-preview` must show the shares the server would compute, by the rule in `stage-1.md` §9, before anything is posted. The preview and submitted split must have identical shares." | invariant | ui_split.py::test_preview_equals_server_shares (order-sensitivity case included) |

### Refresh after actions (SYNC)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-SYNC.1 **H** | Split end | "After any successful action, the balance, the feed and the request lists on the same page must show the new state without a manual reload." | behaviour | ui_sync.py::test_state_refreshes_after_each_action (pay, request, pay-request, decline, cancel, split, authorize, capture, void) |
| R2-SYNC.2 **H** | Split end | "Navigation must wait for the write to succeed before it refreshes the data. Any mechanism is fine, including a full navigation." | behaviour | ui_sync.py::test_refresh_waits_for_write (POST delayed 1.5 s by route; no GET /me before POST completes, final DOM shows new state) |
| R2-SYNC.3 | Split end | "There is no live-update requirement here — another client may change state, but this browser need only refresh after its own action or an explicit refresh." | behaviour | untestable: permission |

### Competing clients and uncertain outcomes (RACE)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-RACE.1 | Competing | "Add `wallet-refresh`, a button on `/` that refreshes the balance and feed without clearing the pay form." | behaviour | ui_race.py::test_refresh_button_keeps_form |
| R2-RACE.2 **H** | Competing | "**Latest refresh wins:** a delayed earlier read must not overwrite a later refresh, including when responses arrive out of order." | behaviour | ui_race.py::test_latest_refresh_wins_out_of_order (route holds 1st GET /me + /activity, 2nd answers after an API payment; release 1st; DOM keeps the 2nd values) |
| R2-RACE.3 **H** | Competing | "A refused payment shows `pay-error`, refreshes the balance/feed, and preserves all pay inputs." | behaviour | ui_race.py::test_refused_payment_refreshes_and_keeps_inputs (balance spent by API behind the page) |
| R2-RACE.4 **H** | Competing | "A request cancelled elsewhere while its pay button is visible must show `request-error` when payment is refused and refresh the request list so the stale pay button disappears." | behaviour | ui_race.py::test_cancelled_elsewhere_pay_shows_error_and_button_disappears |
| R2-RACE.5 **H** | Competing | "If a payment response is lost, including after `POST /payments` commits, show `pay-uncertain` (nonempty text), not `pay-error`." | behaviour | ui_race.py::test_lost_response_after_commit_shows_uncertain (route.fetch then abort) ; ui_race.py::test_lost_request_before_commit_shows_uncertain (abort before forwarding) (D-28) |
| R2-RACE.6 **H** | Competing | "Keep the unchanged form retryable with the **same key and body**." | behaviour | ui_race.py::test_retry_after_uncertain_same_key_same_body (wire capture) |
| R2-RACE.7 **H** | Competing | "Successful retry removes both error/uncertainty elements, refreshes the balance and feed, and moves money exactly once." | behaviour | ui_race.py::test_retry_after_uncertain_same_key_same_body (API balances: one debit; feed one item) |
| R2-RACE.8 **H** | Competing | "Unknown outcomes are not confirmed rejections." | behaviour | ui_race.py::test_lost_response_after_commit_shows_uncertain (pay-error absent) |
| R2-RACE.9 | Competing | "No background polling, live synchronization, or recovery across page reloads is required." | behaviour | untestable: permission |
| R2-RACE.10 **H** | Competing | "The same balance refresh rules apply to the available and held amounts introduced below." | behaviour | ui_race.py::test_latest_refresh_wins_out_of_order (asserts wallet-available/wallet-held too) |

### Existing clients after an upgrade (UPG)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-UPG.1 **H** | Upgrade | "A stage-2 service must accept an export produced by the same team's stage-1 service." | behaviour | api_upgrade.py::test_stage1_export_imports_into_stage2 (export from the stage-1 image on another port → import → 204; /me has total=available=balance, held 0) |
| R2-UPG.2 **H** | Upgrade | "A browser signed in before that export/import upgrade must remain signed in afterwards." | behaviour | ui_upgrade.py::test_browser_stays_signed_in_across_upgrade (D-22) |
| R2-UPG.3 **H** | Upgrade | "Existing pending requests remain payable through the request screen." | behaviour | ui_upgrade.py::test_imported_pending_request_payable_in_ui |
| R2-UPG.4 **H** | Upgrade | "A payment whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original payment and refresh the imported balance." | behaviour | ui_upgrade.py::test_lost_payment_retry_after_upgrade_recovers_original (one debit, retry gets 200 original body, pay-uncertain cleared) |
| R2-UPG.5 | Upgrade | "These requirements apply when import completes between browser requests; migration during an in-flight request is not required." | behaviour | untestable: permission |
| R2-UPG.6 **H** | Upgrade | "No page reload or new screen is required. The form and pending retry identity must survive the upgrade." | behaviour | ui_upgrade.py::test_lost_payment_retry_after_upgrade_recovers_original (no reload between steps; pay inputs unchanged; same key on the wire) |
| R2-UPG.7 **H** | Upgrade + §10 | (derived) a stage-2 export round-trips into stage 2 preserving authorizations, holds, ttl, captures and receipts of all seven paths | behaviour | api_upgrade.py::test_stage2_export_import_preserves_holds_and_receipts |

### Hold invariants and API changes (HOLD)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-HOLD.1 | Authorizations | "A payment may be **authorised** now and **captured** later, for the full amount or less." | behaviour | api_capture.py::test_partial_final_capture_releases_rest |
| R2-HOLD.2 | Authorizations | "An authorisation places a *hold* on the payer's wallet: it reserves money without moving it." | behaviour | api_auth.py::test_authorize_holds_without_moving (total unchanged, held +amount, available −amount; receiver unchanged) |
| R2-HOLD.3 | Authorizations | "Capturing moves the money; a final capture also releases whatever was not captured. Nonfinal captures keep the remainder held." | behaviour | api_capture.py::test_partial_final_capture_releases_rest; api_capture.py::test_nonfinal_keeps_remainder_held |
| R2-HOLD.4 | Authorizations | "An open authorisation expires and releases its remainder on its own." | behaviour | api_expiry.py::test_expiry_releases_without_any_request |
| R2-HOLD.5 **H** | Authorizations | "The sum of all wallet `total` values always equals the total seeded by the last reset. A hold moves no money; payments, settlements and captures transfer money between wallets." | invariant | api_conc.py::test_totals_conserved_mixed_concurrent (every API test also audits sum of totals) |
| R2-HOLD.6 **H** | Authorizations | "`available = total − held` must never be negative." | invariant | api_conc.py::test_available_never_negative_concurrent |
| R2-HOLD.7 **H** | Authorizations | "Held funds cannot fund new payments, authorizations or settlement net debits." | error | api_hold.py::test_held_funds_refuse_payment_authorization_settlement_requestpay (each 409 insufficient_funds when total ≥ amount > available) |
| R2-HOLD.8 **H** | Authorizations | "Captures may spend the money reserved for them." | behaviour | api_hold.py::test_capture_spends_reserved_when_available_zero |
| R2-HOLD.9 **H** | Authorizations | "Cumulative captures must not exceed the authorized amount." | invariant | api_capture.py::test_cumulative_never_exceeds (non-final sequence, concurrent captures) |
| R2-HOLD.10 **H** | Authorizations | "Each idempotent capture moves money once. A closed hold cannot be captured again." | invariant | api_capture.py::test_capture_replay_moves_once; api_capture.py::test_closed_cannot_capture |
| R2-HOLD.11 **H** | API changes | "`GET /me` keeps `balance`, and `balance` **equals `total`**. … With no open holds, `balance`, `total` and `available` agree and `held` is zero, and every earlier behaviour is unchanged." | invariant | api_me.py::test_me_fields_no_holds |
| R2-HOLD.12 **H** | API changes | "`POST /payments` remains an immediate transfer. It must not leave an intermediate hold or require a separate capture." | behaviour | api_hold.py::test_payment_immediate_no_hold (held 0 after; no authorization listed) |
| R2-HOLD.13 **H** | API changes | "Every `409 insufficient_funds` in stage 1 — on `POST /payments`, `POST /requests/{id}/pay` and settlements — is now evaluated against `available`. With no open holds, the result is unchanged." | error | api_hold.py::test_held_funds_refuse_payment_authorization_settlement_requestpay |
| R2-HOLD.14 | API changes | "Paying a request remains immediate. Authorizing a request is out of scope." | behaviour | api_hold.py::test_request_pay_immediate |
| R2-HOLD.15 | API changes | "`POST /splits` is unchanged." | behaviour | carried stage-1 suite (test_splits.py) green on stage 2 |
| R2-HOLD.16 **H** | API changes | "There are now seven idempotent write paths: stage 1's five, authorizations and captures. The same replay rules apply independently to each." | behaviour | api_idem.py (every stage-1 §7 test parametrised over the two new paths: missing key 400, length, replay 200 identical, reuse 409, claimed key before validation, failed-4xx reuse, per-user, per-path, 20 concurrent → one 201) |

### Fixture model (MOD)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-MOD.1 | Model | "The fixture gains a service-wide default lifetime and an `authorizations` array." (`id`, `from_user_id`, `to_user_id`, `amount`, `note`, `visibility`, `status`, `expires_at`) | format | api_model.py::test_seeded_authorization_visible_with_fixture_fields |
| R2-MOD.2 **H** | Model | "`authorization_ttl_seconds` applies to every authorisation created through the API. It defaults to 600 when omitted." | behaviour | api_auth.py::test_expires_at_is_created_plus_ttl[600 default, 2, 3600] |
| R2-MOD.3 **H** | Model | "If supplied, it must be a positive integer number of seconds." | error | api_model.py::test_ttl_invalid_reset_422 (0, −1, 1.5, "600", true, null) (D-29) |
| R2-MOD.4 | Model | "Seeded authorisations carry their own absolute `expires_at` instead." | behaviour | api_model.py::test_seeded_expires_at_kept_verbatim_instant |
| R2-MOD.5 **H** | Model | "A user's seeded `balance` is still `total`. **`available` is derived, never seeded** — the service subtracts the seeded open holds itself." | behaviour | api_model.py::test_seeded_open_hold_reduces_available (total = balance, available = balance − hold) |
| R2-MOD.6 **H** | Model | "A sum of seeded unexpired open holds larger than that user's `balance` is a reset error: `422 validation_failed` from `POST /_test/reset`, changing nothing, exactly like a negative seeded balance." | error | api_model.py::test_seeded_holds_over_balance_422_state_unchanged (sum = balance → 204; sum = balance+1 → 422; expired/voided/captured over balance → 204) |
| R2-MOD.7 | Model | "Seeded `status` is `open`, `captured`, `voided` or `expired`. Only `open` holds anything." | behaviour | api_model.py::test_seeded_statuses_only_open_holds; api_model.py::test_seeded_status_invalid_422 |
| R2-MOD.8 **H** | Model | "An earlier fixture may omit `authorizations` altogether; omission means an empty list." | behaviour | carried stage-1 suite uses stage-1 fixtures unchanged; api_model.py::test_fixture_without_authorizations |
| R2-MOD.9 **H** | Model | (derived, D-30) seeded authorizations referencing unknown users, self-authorizations, invalid amount/visibility/expires_at, duplicate ids → 422 changing nothing | error | api_model.py::test_seeded_authorization_invalid_422 |

### Expiry (EXP)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-EXP.1 **H** | Model | "An authorization whose `expires_at` is at or before now is `expired` and holds no funds." | behaviour | api_expiry.py::test_expired_holds_nothing (seeded past expires_at: status expired, held 0, available = total) |
| R2-EXP.2 **H** | Model | "Reads and writes must reflect expiry even if no request occurred at the deadline." | behaviour | api_expiry.py::test_expiry_releases_without_any_request (ttl 2 s; no request for 3 s; then /me, list, capture, payment of the released funds) |
| R2-EXP.3 **H** | Model | "`GET /authorizations` must show `status: "expired"`, and `GET /me` must include the released remainder in `available`." | behaviour | api_expiry.py::test_expiry_releases_without_any_request; api_expiry.py::test_partial_nonfinal_then_expiry_releases_only_remainder |
| R2-EXP.4 | Model | "Seeded expiry times are at least an hour from reset time, in the past or future; newly created authorizations may have shorter lifetimes." | limit | api_expiry.py fixtures use ±1 h seeded, ttl 2 s for API-created |
| R2-EXP.5 **H** | Capture | "`expires_at` is at or before now \| 409 `authorization_expired`" | error | api_expiry.py::test_capture_after_expiry_409_expired (D-31 precedence) |
| R2-EXP.6 **H** | LIST | "An authorisation expired by the clock matches `expired`, never `open`." | behaviour | api_list.py::test_clock_expired_filters_as_expired |
| R2-EXP.7 **H** | Upgrade + §10 | (derived) expiry continues by absolute time across export/import | behaviour | api_upgrade.py::test_stage2_export_import_preserves_holds_and_receipts |

### GET /me (ME)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-ME.1 | GET /me | `{ "user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units" }` | format | api_me.py::test_me_shape_with_seeded_hold (example values 10000/10000/8000/2000) |
| R2-ME.2 **H** | GET /me | "`balance` and `total` are always equal. `held` is the sum of open holds, and `available` is `total − held`, never negative." | invariant | api_me.py::test_me_identities_after_every_operation (helper asserts on every /me read in the suite) |

### POST /authorizations (AUTH)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-AUTH.1 | POST /auth | "`Idempotency-Key` is required. The caller is the payer." | behaviour | api_idem.py[authorizations]; api_auth.py::test_authorize_201_shape |
| R2-AUTH.2 | POST /auth | body `{ "to_handle", "amount", "note", "visibility" }`; "`note` and `visibility` are optional with the same defaults as `POST /payments`." | behaviour | api_auth.py::test_authorize_defaults |
| R2-AUTH.3 **H** | POST /auth | 201 body: authorization_id, from_user_id, from_handle, to_user_id, to_handle, amount, captured_amount 0, currency, note, visibility, status "open", expires_at, payment_id null, created_at — plus `remaining_amount` and `payment_ids` (capture section) | format | api_auth.py::test_authorize_201_shape (exact key set) (D-32) |
| R2-AUTH.4 **H** | POST /auth | "`expires_at` is `created_at` plus `authorization_ttl_seconds`." | behaviour | api_auth.py::test_expires_at_is_created_plus_ttl |
| R2-AUTH.5 | POST /auth | "The caller's `available` is below `amount` \| 409 `insufficient_funds`" | error | api_auth.py::test_authorize_insufficient_available_409 (exact available ok; available+1 → 409; held funds don't count) |
| R2-AUTH.6 | POST /auth | "`amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed`" | error | api_auth.py::test_authorize_amount_rules (0, 1e9+1, 1.5, "5", true, null; 1e3/1000.0 accepted) |
| R2-AUTH.7 | POST /auth | "`to_handle` is the caller's own handle \| 422 `self_payment`" | error | api_auth.py::test_authorize_self_422 |
| R2-AUTH.8 | POST /auth | "`note` over 200 characters, or `visibility` neither `public` nor `private` \| 422 `validation_failed`" | error | api_auth.py::test_authorize_note_visibility_rules (incl. note null) |
| R2-AUTH.9 | POST /auth | "No user has that handle \| 404 `not_found`" | error | api_auth.py::test_authorize_unknown_handle_404 |
| R2-AUTH.10 **H** | POST /auth | "An open authorisation is **not** a feed item and never appears in `GET /activity`." | behaviour | api_auth.py::test_open_authorization_not_in_feed (all users' feeds) |

### Capture (CAP)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-CAP.1 | Capture | "`Idempotency-Key` is required. Only the receiver (the `to` party) may capture." | behaviour | api_idem.py[capture]; api_capture.py::test_payer_or_third_party_capture_403 |
| R2-CAP.2 **H** | Capture | "`amount` is optional and defaults to the authorisation's remaining amount." | behaviour | api_capture.py::test_capture_default_amount_is_remaining (fresh and after a non-final capture) |
| R2-CAP.3 **H** | Capture | "**a replay must send the identical body** — `{}` and `{"amount": 2000}` are different JSON values even when they mean the same capture, so reusing a key across the two is 409 `idempotency_key_reuse`" | error | api_capture.py::test_empty_vs_explicit_amount_reuse_409 (also `{}` vs `{"final":true}`) |
| R2-CAP.4 **H** | Capture | "Returns `201` with the created **payment**, in exactly the shape `POST /payments` returns, with `authorization_id` set to this authorisation and `request_id: null`." | format | api_capture.py::test_capture_returns_payment_shape (PAYMENT_KEYS + authorization_id; settlement_id null) |
| R2-CAP.5 | Capture | "The payment's `amount` is the captured amount; its `note` and `visibility` are copied from the authorisation; it appears in the activity feed by the ordinary visibility rule." | behaviour | api_capture.py::test_capture_payment_in_feed_by_rule (private auth → third party can't see) |
| R2-CAP.6 **H** | Capture | "Payments created without an authorisation carry `authorization_id: null`; their existing `request_id` semantics are unchanged." | format | api_capture.py::test_noncapture_payments_authorization_id_null (direct, request pay, settlement member, seeded) |
| R2-CAP.7 | Capture | "By default the authorisation becomes `captured`, carries `captured_amount` and `payment_id`, and **releases the uncaptured remainder immediately**: capturing 1500 of 2000 returns 500 to the payer's `available` in the same step." | behaviour | api_capture.py::test_partial_final_capture_releases_rest (payer total −1500, held 0, available +500 vs before capture; receiver +1500) |
| R2-CAP.8 | Capture | "**Default: one final capture per authorisation.** A second capture after a final capture is `409 authorization_not_open`." | error | api_capture.py::test_closed_cannot_capture |
| R2-CAP.9 **H** | Capture | "To keep the remainder held, send `{"amount": 700, "final": false}`. `final` is boolean, default `true`" | behaviour | api_capture.py::test_nonfinal_keeps_remainder_held; api_capture.py::test_final_wrong_type_400 (D-33) |
| R2-CAP.10 **H** | Capture | "With `final: false` and an uncaptured remainder, status stays `open`; further captures are allowed up to that remainder. Capturing the entire remainder closes it even with `final: false`." | behaviour | api_capture.py::test_nonfinal_sequence_closes_at_full |
| R2-CAP.11 **H** | Capture | "A final capture closes it and releases any remainder." | behaviour | api_capture.py::test_nonfinal_then_final_releases_rest |
| R2-CAP.12 **H** | Capture | "`capture_exceeds_authorization` compares with the **remaining** amount; omitted amount defaults to that remainder." | error | api_capture.py::test_exceeds_compares_remaining (2000 auth, 700 non-final, then 1301 → 422; 1300 ok) |
| R2-CAP.13 **H** | Capture | "`captured_amount` is cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order." | format | api_capture.py::test_cumulative_fields_after_each_capture |
| R2-CAP.14 **H** | Capture | "Every authorization response adds `remaining_amount`: the amount still held, zero when closed." | format | api_capture.py::test_remaining_amount_everywhere (create, list, void, capture-closed, expired) |
| R2-CAP.15 **H** | Capture | "Void and expiry can close a partially captured authorization, release only the remainder, and preserve all capture records." | behaviour | api_void.py::test_void_after_nonfinal_keeps_captures; api_expiry.py::test_partial_nonfinal_then_expiry_releases_only_remainder |
| R2-CAP.16 **H** | Capture | "New fields do not change idempotency body equality." | behaviour | api_capture.py::test_replay_returns_original_even_after_more_captures (D-34) |
| R2-CAP.17 | Capture | "The authorisation is not `open` \| 409 `authorization_not_open`" | error | api_capture.py::test_closed_cannot_capture (captured, voided) |
| R2-CAP.18 | Capture | "`amount` above the authorisation's uncaptured remainder \| 422 `capture_exceeds_authorization`" | error | api_capture.py::test_exceeds_compares_remaining |
| R2-CAP.19 | Capture | "`amount` below 1, or not an integer \| 422 `validation_failed`" | error | api_capture.py::test_capture_amount_rules (0, −1, 1.5, "5", true, null) |
| R2-CAP.20 | Capture | "The caller is not the receiver \| 403 `forbidden`" | error | api_capture.py::test_payer_or_third_party_capture_403 |
| R2-CAP.21 | Capture | "Unknown authorisation \| 404 `not_found`" | error | api_capture.py::test_unknown_authorization_404 |
| R2-CAP.22 **H** | Capture | (derived, D-31) precedence: 401 → 400 body → 400/422 key → replay/reuse → 400 `final` type / 422 amount rules → 404 → 403 → 409 not_open / expired → 422 capture_exceeds | error | api_capture.py::test_capture_precedence |

### Void (VOID)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-VOID.1 | Void | "**Only the payer may void** — the `from` party releasing their own hold. No idempotency key, like decline and cancel." | behaviour | api_void.py::test_void_by_payer_no_key |
| R2-VOID.2 | Void | "`200` with the authorisation, `status: "voided"`, the hold released." | behaviour | api_void.py::test_void_by_payer_no_key (available restored, total unchanged) |
| R2-VOID.3 **H** | Void | "Voiding an already-voided authorisation is `200` with the current state." | behaviour | api_void.py::test_void_twice_200 |
| R2-VOID.4 **H** | Void | "A `captured` or `expired` one is `409 authorization_not_open`." | error | api_void.py::test_void_captured_or_expired_409 (clock-expired and seeded expired) |
| R2-VOID.5 **H** | Void | "For an existing authorization, capture and void return 403 `forbidden` when the caller is not the permitted party, including callers who are neither party." | error | api_void.py::test_receiver_or_third_party_void_403; api_capture.py::test_payer_or_third_party_capture_403 |
| R2-VOID.6 | Void | (derived) unknown authorization id → 404 `not_found` | error | api_void.py::test_unknown_void_404 |

### GET /authorizations (LIST)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-LIST.1 | LIST | "`GET /authorizations` returns only authorizations involving the caller." / "Authorisations where the caller is the payer or the receiver, and no others." | invariant | api_list.py::test_only_own_authorizations |
| R2-LIST.2 | LIST | "Newest first by `created_at`." | behaviour | api_list.py::test_newest_first |
| R2-LIST.3 **H** | LIST | "`direction` is `outgoing` (the caller is the payer), `incoming` (the caller is the receiver), or absent for both." | behaviour | api_list.py::test_direction_filter |
| R2-LIST.4 | LIST | "`status` is one of the four statuses, or absent for all." | behaviour | api_list.py::test_status_filter_all_four; api_list.py::test_unknown_direction_status_422 |
| R2-LIST.5 | LIST | "`limit`, `offset` and `has_more` behave exactly as on `GET /requests`." | limit | api_list.py::test_limit_offset_has_more (bounds, plain digits, huge offset valid L3) |
| R2-LIST.6 | LIST | (derived) response `{"authorizations": [...], "has_more": bool}` | format | api_list.py::test_list_shape (D-35) |

### Authorizations UI (AUI)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-AUI.1 | UI | "A new route `/authorizations`, and the wallet gains two numbers." | screen | ui_routes.py::test_required_routes_render_html[/authorizations] |
| R2-AUI.2 | UI | "`wallet-balance` \| Formatted `total`, retaining the existing display and `data-amount`" | screen | ui_wallet.py::test_wallet_numbers_with_hold |
| R2-AUI.3 **H** | UI | "`wallet-available` \| Formatted `available`, with `data-amount`. **Present this as the headline number** — it is what the user can actually spend" | screen | ui_wallet.py::test_wallet_numbers_with_hold; ui_visual.py::test_available_is_headline |
| R2-AUI.4 **H** | UI | "`wallet-held` \| Formatted `held`, with `data-amount`. Absent when `held` is zero" | screen | ui_wallet.py::test_wallet_held_absent_when_zero_present_with_hold |
| R2-AUI.5 | UI | "`authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` \| The authorise form. Same input rules as the pay form" | screen | ui_authz.py::test_authorize_form_creates_hold |
| R2-AUI.6 | UI | "`authorize-error` \| Shown when the authorisation is refused, including insufficient available funds" | screen | ui_authz.py::test_authorize_error_insufficient_available |
| R2-AUI.7 | UI | "`authorization-list` \| Container on `/authorizations`. Children newest first in the DOM" | screen | ui_authz.py::test_authorization_list_newest_first |
| R2-AUI.8 | UI | "`authorization-item-{authorization_id}` \| Carries `data-status="{status}"`" | screen | ui_authz.py::test_items_status_incl_clock_expired |
| R2-AUI.9 | UI | "`authorization-amount-{id}` \| Text is exactly the formatted authorised amount" | format | ui_authz.py::test_item_fields_exact |
| R2-AUI.10 **H** | UI | "`authorization-captured-{id}` \| Formatted captured amount. Present only when `status` is `captured`" | screen | ui_authz.py::test_captured_element_only_when_captured (absent on open-with-partial and voided-with-partial) |
| R2-AUI.11 **H** | UI | "`authorization-expires-{id}` \| Text is the RFC 3339 `expires_at`" | format | ui_authz.py::test_item_fields_exact (text == API expires_at) (D-36) |
| R2-AUI.12 **H** | UI | "`authorization-capture-amount-{id}` \| Decimal input, pre-filled with the remaining amount. Present only on an incoming `open` authorisation" | screen | ui_authz.py::test_capture_controls_only_incoming_open (prefill `15.00` style, updates after non-final capture) (D-36) |
| R2-AUI.13 | UI | "`authorization-capture-{id}` \| Button. Present only on an incoming `open` authorisation" | screen | ui_authz.py::test_capture_controls_only_incoming_open |
| R2-AUI.14 | UI | "`authorization-void-{id}` \| Button. Present only on an outgoing `open` authorisation" | screen | ui_authz.py::test_void_button_only_outgoing_open |
| R2-AUI.15 | UI | "`authorization-error` \| Shown when a capture or a void is refused" | screen | ui_authz.py::test_capture_refused_shows_error (expired behind the page; exceeds remainder) |
| R2-AUI.16 | UI | "`empty-authorizations` \| Shown when the list is empty" | screen | ui_states.py::test_empty_states |
| R2-AUI.17 **H** | UI | "The UI must reflect seeded and newly created holds. Show available funds as the user's spending balance, including immediately after reset with open holds." | screen | ui_wallet.py::test_seeded_hold_shown_right_after_reset |
| R2-AUI.18 | UI | (derived) capture from the UI submits the decimal input as minor units with an Idempotency-Key; non-final capture is not required in the UI | behaviour | ui_authz.py::test_capture_from_ui_partial (D-37) |

### Concurrency (CONC)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R2-CONC.1 **H** | Concurrent | "Concurrent requests must produce the same results as executing them one at a time in some order, and the requirements above hold at every read." | invariant | api_conc.py::test_capture_vs_void_race_single_outcome; api_conc.py::test_concurrent_captures_never_exceed; api_conc.py::test_authorize_vs_payment_available_never_negative; api_conc.py::test_totals_conserved_mixed_concurrent (reader threads assert ME identities on every read during load) |

## Part B — stage 1 rows changed by stage 2

Stage-1 rows not listed here are unchanged and carried. The carried stage-1 acceptance suite
(`stage-2/acceptance/stage1/`) is updated only where a row below changes, each with a decision
record citing the stage 2 row.

| id | stage 1 rule (short) | changed by | new rule |
|---|---|---|---|
| R-1.6 | sum of balances = seeded total | R2-HOLD.5 | sum of `total` (= `balance`) = seeded total; holds move nothing |
| R-1.7 | no negative balance | R2-HOLD.6 | `total ≥ 0` and `available = total − held ≥ 0` at every read |
| R-3.5 | reset replaces state with fixture | R2-MOD.1–9 | fixture adds `authorization_ttl_seconds` and `authorizations`; holds over balance → 422 |
| R-3.8 | requests and responses are JSON | R2-SCR.2/5/6 | UI routes return HTML; `/requests` and `/authorizations` negotiate on `Accept: text/html` |
| R-3.12 | ids ≤ 64 chars | R2-AUTH.3 | applies to authorization ids too |
| R-3.13 | generated ids never collide with fixture ids | R2-MOD.1 | applies to seeded authorization ids |
| R-4.29 | fixture shape | R2-MOD.1 | + `authorization_ttl_seconds`, `authorizations[]` |
| R-7.1 | five idempotent paths | R2-HOLD.16 | seven paths (+ `POST /authorizations`, `POST /authorizations/{id}/capture`) |
| R-8.1 | `GET /me` shape | R2-ME.1 | + `total`, `available`, `held` |
| R-8.5 | payment key set | R2-CAP.4/6 | + `authorization_id` (null unless a capture) on every payment object |
| R-8.6 | payments 409 when balance < amount | R2-HOLD.13 | compared with `available` |
| R-8.26 | pay returns payment shape | R2-CAP.6 | payment carries `authorization_id: null` |
| R-8.29 | request pay 409 when balance < amount | R2-HOLD.13 | compared with `available` |
| R-8.41/R-8.48 | `GET /requests` JSON list | R2-SCR.5 | JSON unless `Accept: text/html` |
| R-8.62 | feed items are payment objects | R2-CAP.4/6 | items carry `authorization_id`; captures appear, open authorizations never |
| R-10.2 | export `{track, format_version: 1, state}` | R2-UPG.1/7 | unchanged envelope (D-38); state also carries holds, ttl |
| R-10.3/R-10.11 | import accepts own export, preserves everything | R2-UPG.1–7 | also accepts the stage-1 service's export; preserves authorizations, holds, captures |
| R-10.16 | import removes destination credentials | R2-UPG.2 | see D-22 (signed-in browser across the upgrade) |
| R-11.11/R-11.12 | settlement affordable on net ≥ 0 of balance | R2-HOLD.7/13 | net debit must fit within `available` |
| R-11.16 | members carry settlement_id | R2-CAP.6 | members also carry `authorization_id: null` |
| R-X.1 | precedence | R2-CAP.22 | extended to authorization/capture paths |

## Coverage table

| area | rows | tested (api) | tested (ui) | review / untestable | hidden (H) |
|---|---|---|---|---|---|
| SCR | 8 | 2 | 5 | 1 | 3 |
| VIS | 13 | 0 | 11 | 2 | 7 |
| SIGN | 6 | 0 | 6 | 0 | 3 |
| PAY | 8 | 0 | 8 | 0 | 3 |
| AMT | 8 | 0 | 8 | 0 | 7 |
| FEED | 8 | 0 | 7 | 1 | 3 |
| REQ | 8 | 0 | 8 | 0 | 2 |
| SPL | 6 | 0 | 6 | 0 | 4 |
| SYNC | 3 | 0 | 2 | 1 | 2 |
| RACE | 10 | 0 | 9 | 1 | 8 |
| UPG | 7 | 2 | 4 | 1 | 6 |
| HOLD | 16 | 16 | 0 | 0 | 10 |
| MOD | 9 | 9 | 0 | 0 | 6 |
| EXP | 7 | 7 | 0 | 0 | 6 |
| ME | 2 | 2 | 0 | 0 | 1 |
| AUTH | 10 | 10 | 0 | 0 | 3 |
| CAP | 22 | 22 | 0 | 0 | 13 |
| VOID | 6 | 6 | 0 | 0 | 3 |
| LIST | 6 | 6 | 0 | 0 | 1 |
| AUI | 18 | 0 | 18 | 0 | 6 |
| CONC | 1 | 1 | 0 | 0 | 1 |
| **Total** | **182** | **83** | **92** | **7** | **98** |

Review/untestable rows: R2-SCR.4, R2-VIS.4, R2-VIS.13, R2-FEED.7, R2-SYNC.3, R2-RACE.9,
R2-UPG.5 (permissions; R2-VIS.4 is review only). R2-VIS.1 is counted as ui (screenshots taken
for the verifier's review), as are R2-VIS.3/R2-VIS.6 for their automatable part. Recompute rows with `grep -c '^| R2-' ledger.md`.

## Hidden requirements to watch

Latest-refresh-wins with out-of-order responses (R2-RACE.2/10) · `pay-uncertain` after a
committed-but-lost response and same-key, same-body retry (R2-RACE.5–8) · form and retry
identity surviving a stage-1→stage-2 export/import without reload (R2-UPG.2/4/6) · decimal
input rules incl. `15.005` and `minor_units` 0/3 (R2-AMT.6–8) · exact formatted amounts,
no grouping, no sign (R2-AMT.2–5, FEED.4, REQ.3, SPL.4, AUI.9) · expiry evaluated at read
time with no request at the deadline (R2-EXP.2/3/6) · seeded open holds over balance → reset
422 (R2-MOD.6) · `available` derived, never seeded (R2-MOD.5) · held funds refuse payments,
request pay, authorizations and settlement net debits (R2-HOLD.7/13) · `{}` vs
`{"amount": n}` reuse 409 (R2-CAP.3) · `capture_exceeds_authorization` against the remainder
(R2-CAP.12) · `authorization_id: null` on every non-capture payment (R2-CAP.6) · 403 (not
404) for third parties on capture/void (R2-VOID.5) · `direction` meaning inverted vs requests
(R2-LIST.3) · `wallet-held` absent at zero (R2-AUI.4) · `authorization-captured` only when
`captured` (R2-AUI.10) · 375 px with no horizontal scroll, visible labels, focus, contrast
(R2-VIS.7–10) · Accept negotiation on `/requests` and `/authorizations` (R2-SCR.5/6) · same
results as some serial order (R2-CONC.1).

## Risk list — the five most likely to be built wrong

1. **R2-UPG.2/4/6 upgrade continuity.** The browser's session, its in-memory pay form and the
   pending Idempotency-Key must survive a stage-1 export imported into the stage-2 service with
   no reload. Stage 1's import removes destination credentials (R-10.16); unless the session
   the browser holds is one that the stage-1 export contains, the browser is logged out
   (D-22). The retry must then get 200 with the stored stage-1 receipt (which lacks
   `authorization_id`) and the UI must accept it as success.
2. **R2-RACE.2/5/6 client state machine.** Latest-refresh-wins needs a per-read sequence guard
   (not "last response wins"); lost responses (network error, abort after commit, 5xx) must
   produce `pay-uncertain`, keep the key, and retry with the byte-identical JSON value; only a
   field change mints a new key.
3. **R2-EXP.2/3, R2-MOD.5/6 time-derived holds.** `held`/`available`/status must be computed
   from `expires_at` vs now on every read and write (no sweeper dependency), including in list
   filters, capture (409 `authorization_expired`), void (409 `authorization_not_open`), the
   seeded-holds-over-balance check (only unexpired open holds count), and settlement/payment
   affordability.
4. **R2-CAP.2/3/9–14 capture arithmetic.** Default amount = remaining; final default true;
   non-final keeps remainder open; full remainder closes even when non-final; exceeds compares
   with remaining; cumulative `captured_amount`, latest `payment_id`, ordered `payment_ids`,
   `remaining_amount` 0 when closed; `{}` ≠ `{"amount": n}` ≠ `{"final": true}` for replay.
5. **R2-AMT/R2-SPL.6 money formatting and preview.** Decimal parsing without floats (string
   arithmetic), rejection of `15.005`/nonnumeric without a request, exact `minor_units`
   formatting (`1200 JPY`, `1.500 BHD`), and a client-side §9 preview identical to the
   server's shares in handle order.

Runner-up: R2-VIS.7–10 at 375 px (long notes, 1e9 amounts and handles of 20 characters must
wrap, not scroll) and contrast/focus on every control.
