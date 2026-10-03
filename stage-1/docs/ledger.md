# Stage 1 requirements ledger — Pocketful: payments and settlements

Source of truth: `runlog/stage1-spec.md` (stage 1 specification, §1–§11). Nothing else.

- **id**: `R-<section>.<n>`, stable once published; never renumbered. New rows get new numbers.
- **kind**: behaviour, error, invariant, limit, format, operational.
- **proof**: the acceptance test (file under `stage-1/acceptance/`, test name), or
  `untestable: <reason>`. `ops:` proofs are run by the verifier against the built image
  (docker), not by the HTTP suite.
- **H** = hidden: a requirement that a quick reading or a shipped sample check is unlikely
  to ask about. These are where the stage is lost.
- Where the text is open, the reading taken is in `docs/decisions/` and cited as `D-nn`.

## 1. Scope

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-1.1 | §1 | "Users can send money by handle, request money and split bills." | behaviour | test_payments.py::test_send_by_handle_201; test_requests.py::test_create_request_201; test_splits.py::test_split_example_3000_3 |
| R-1.2 | §1 | "Payments appear in an activity feed with public or private visibility." | behaviour | test_activity.py::test_feed_contract_matrix |
| R-1.3 | §1 | "Authorized operators can submit groups of transfers as settlements." | behaviour | test_settlements.py::test_operator_settlement_201 |
| R-1.4 | §1 | "Only the HTTP API is required." | operational | untestable: scope statement, nothing to observe |
| R-1.5 | §1 | "The following apply to all operations, including concurrent requests and retries" | invariant | test_invariants.py (every test runs the R-1.6/R-1.7 audit after its workload) |
| R-1.6 | §1 | "The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`." | invariant | test_invariants.py::test_sum_conserved_concurrent_mixed_load; test_invariants.py::test_sum_conserved_after_splits_paid; test_settlements.py::test_sum_conserved_after_settlement |
| R-1.7 | §1 | "No wallet balance may be negative, including transiently." | invariant | test_invariants.py::test_concurrent_overspend_one_wins; test_invariants.py::test_crossing_payments_never_negative; (transient part: untestable directly, proven by zero-balance-probe under load, see test) |
| R-1.8 | §1 | "A payment request may move money at most once." | invariant | test_invariants.py::test_concurrent_pay_distinct_keys_one_payment; test_invariants.py::test_pay_vs_cancel_race_single_outcome |
| R-1.9 | §1 | "All amounts are exact integer counts of minor units." | format | test_payments.py::test_amount_returned_as_json_integer |
| R-1.10 | §1 | "Money moves only between existing wallets." | invariant | test_payments.py::test_unknown_handle_404_no_movement |
| R-1.11 | §1 | "Deposits, top-ups, withdrawals, cards and bank integrations are out of scope." | operational | untestable: absence of out-of-scope features is not judged |

## 2. Delivery and deployment

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-2.1 | §2 | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup." | operational | ops: test_operational.py::test_dockerfile_and_runmd_exist; verifier runs the RUN.md command verbatim |
| R-2.2 | §2 | "The harness builds the submitted `Dockerfile`, starts the resulting image and tests only its HTTP behavior" | operational | ops: verifier `docker build` + `docker run` |
| R-2.3 | §2 | "The image must run on its own with `-e PORT=<port>` and a port mapping." | operational | ops: `docker run -e PORT=18150 -p 18150:18150` then GET /health |
| R-2.4 | §2 | "Runtime networking has no outbound access. All runtime dependencies, initialization and seed data must work within that single container." | operational | ops: `docker run --network none` (with port reached via `docker exec`/internal curl) or a no-egress network; full suite passes |
| R-2.5 | §2 | "Compose configuration is not used to start the service." | operational | ops: image started without compose |
| R-2.6 | §2 | "CPU \| 2 vCPU" / "Memory \| 2 GiB" | limit | ops: run with `--cpus 2 --memory 2g`; full suite passes |
| R-2.7 | §2 | "Start to first healthy response \| 60 s" | limit | ops: test_operational.py::test_healthy_within_60s |
| R-2.8 | §2 | "Concurrent requests \| up to 50 in flight" | limit | test_invariants.py::test_50_in_flight_no_5xx_within_timeout |
| R-2.9 **H** | §2 | "Per-request timeout \| 5 s (10 s for `POST /_test/reset`)" | limit | test_invariants.py::test_50_in_flight_no_5xx_within_timeout (5 s client timeout); test_auth.py::test_50_concurrent_logins_within_5s; test_reset.py::test_large_fixture_reset_within_10s |
| R-2.10 | §2 | "Outbound network \| available during `docker build`, **none at run time**" | operational | ops: as R-2.4 |
| R-2.11 | §2 | "Disk \| ephemeral; state need not survive a container restart" | operational | untestable: permission, not an obligation |
| R-2.12 | §2 | "Runtime assets and dependencies must be included in the image. This includes fonts, scripts and stylesheets; external services are unavailable at runtime." | operational | ops: as R-2.4 |

## 3. Runtime contract

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-3.1 | §3.1 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | operational | ops: run with and without `-e PORT`; GET /health via mapped port |
| R-3.2 | §3.2 | "GET /health  ->  200  {"status": "ok"}" | behaviour | test_runtime.py::test_health_200_status_ok |
| R-3.3 | §3.2 | "Return 200 once the service and its data store can serve requests, within 60 seconds of container start. Non-200 responses are permitted before the service is ready." | operational | ops: test_operational.py::test_healthy_within_60s |
| R-3.4 | §3.3 | "POST /_test/reset ... ->  204 No Content" | behaviour | test_reset.py::test_reset_204_empty_body |
| R-3.5 | §3.3 | "Replace all service state with the fixture in the request body (§4). When reset returns 204, subsequent requests must see only that fixture." | behaviour | test_reset.py::test_reset_replaces_users_old_token_401; test_reset.py::test_reset_drops_old_payments_requests |
| R-3.6 | §3.3 | "Repeated resets are supported." | behaviour | test_reset.py::test_repeated_resets |
| R-3.7 | §3.3 | "This test endpoint must be enabled in the delivered image and requires no authentication." | behaviour | test_reset.py::test_reset_without_auth |
| R-3.8 **H** | §3.4 | "Requests and responses are `application/json; charset=utf-8`." | format | test_runtime.py::test_content_type_json_utf8_on_success_and_error |
| R-3.9 **H** | §3.4 | "Timestamps in responses are RFC 3339 with an explicit offset, e.g. `2026-09-24T19:00:00+02:00`." | format | test_payments.py::test_created_at_rfc3339_with_offset (all timestamp fields: created_at, committed_at) |
| R-3.10 **H** | §3.4 | "Unknown fields in a request body are ignored, never an error." | behaviour | test_payments.py::test_unknown_fields_ignored_cannot_spoof_sender; test_reset.py::test_fixture_unknown_fields_ignored; test_settlements.py::test_unknown_fields_ignored |
| R-3.11 | §3.4 | "Unknown query parameters are ignored." | behaviour | test_activity.py::test_unknown_query_param_ignored; test_requests.py::test_list_unknown_query_param_ignored |
| R-3.12 **H** | §3.4 | "IDs are opaque strings of at most 64 characters. Their format is yours." | format | test_payments.py::test_ids_are_strings_le_64 (payment, request, split, settlement, user ids) |
| R-3.13 **H** | §3.4 + §4 | (derived) generated IDs must never collide with fixture-supplied IDs (`p_1`, `rq_1`, `u_ada` are caller-chosen). | invariant | test_reset.py::test_generated_ids_do_not_collide_with_fixture_ids |

## 4. Model

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-4.1 | §4 | "The service has **one currency**, declared in the fixture." | behaviour | test_runtime.py::test_me_currency_from_fixture (EUR, JPY, BHD) |
| R-4.2 | §4 | "Every amount in the API is an integer count of its minor units" | format | test_payments.py::test_amount_returned_as_json_integer |
| R-4.3 **H** | §4 | "API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount." | behaviour | test_payments.py::test_amount_float_forms_accepted (1000.0, 1e3 -> 201, amount 1000 debited, response amount 1000); same for requests, splits, settlements |
| R-4.4 **H** | §4 | "Booleans and strings are not numbers here." | error | test_payments.py::test_amount_bool_or_string_422 (true, "1000") |
| R-4.5 | §4 | "Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set." | invariant | test_auth.py::test_me_handle_stable; test_auth.py::test_signup_handle_collision_409 |
| R-4.6 | §4 | "Users identify recipients by handle. Directory and user-search endpoints are out of scope." | behaviour | test_payments.py::test_send_by_handle_201 |
| R-4.7 | §4 | "Seeded users take their handle from the fixture." | behaviour | test_runtime.py::test_me_shape_seeded |
| R-4.8 **H** | §4 | "take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters." | behaviour | test_auth.py::test_derived_handle_rules ("Ada.Lovelace+x@..." -> "ada_lovelace_x"; 25-char local -> first 20; "é" -> "_") |
| R-4.9 | §4 | "If that handle is already taken the signup fails" | error | test_auth.py::test_signup_handle_collision_409 |
| R-4.10 | §4 | "New users start with a balance of `0`. They can receive money and be asked for money immediately." | behaviour | test_auth.py::test_signup_balance_zero_can_receive_and_be_asked |
| R-4.11 | §4 | "A **payment** moves money from one wallet to another, immediately and atomically. It is either sent directly or created by paying a request." | behaviour | test_payments.py::test_balances_move_immediately; test_requests.py::test_pay_creates_payment_with_request_id |
| R-4.12 | §4 | "A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`." | invariant | test_requests.py::test_terminal_states_are_final (paid/declined/cancelled cannot transition) |
| R-4.13 | §4 | "Only the payer may pay or decline it; only the requester may cancel it." | error | test_requests.py::test_requester_cannot_pay_403; test_requests.py::test_requester_cannot_decline_403; test_requests.py::test_payer_cannot_cancel_403 |
| R-4.14 **H** | §4 | "**A request may exceed the payer's balance.** That is a legal state, not an error at creation time" | behaviour | test_requests.py::test_request_above_payer_balance_201_pending |
| R-4.15 **H** | §4 | "an attempt to pay it while short is `409 insufficient_funds` and changes nothing. Money can arrive later and the same request then becomes payable." | behaviour | test_requests.py::test_pay_short_409_then_funded_201 (same key reused after the 409 -> 201, see R-7.9) |
| R-4.16 | §4 | "**Visibility belongs to the payment, not the request.** The payer chooses it when the money moves." | behaviour | test_requests.py::test_pay_visibility_private_sets_payment |
| R-4.17 | §4 | "A request carries no visibility of its own and never appears in anyone else's feed." | behaviour | test_activity.py::test_requests_never_in_feed; test_requests.py::test_request_has_no_visibility_field (D-07) |
| R-4.18 | §4 | "`GET /activity` returns payments only. A payment appears for a caller **if and only if** its `visibility` is `public`, **or** the caller is its sender or its receiver." | invariant | test_activity.py::test_feed_contract_matrix (public/private × sender/receiver/third party, incl. seeded payments) |
| R-4.19 | §4 | "There is no other rule, no follow graph and no mute list." | behaviour | test_activity.py::test_third_party_sees_public_between_strangers |
| R-4.20 | §4 | "Requests never appear in the activity feed; they are read through `GET /requests`, which returns only requests where the caller is the requester or the payer." | invariant | test_requests.py::test_list_only_own_requests |
| R-4.21 | §4 | "A split is not a feed item. The requests it creates are visible to their own two parties, and the payments that eventually fulfil them follow the rule above." | behaviour | test_splits.py::test_split_not_in_feed_requests_visible_to_parties |
| R-4.22 **H** | §4 | "Visibility is **one value on the payment**, seen identically by both parties and by everyone else. A `private` payment is hidden from third parties, not from its own receiver." | invariant | test_activity.py::test_private_visible_to_receiver_same_value |
| R-4.23 **H** | §4 | "`amount` is at most `1000000000` on any single request" | limit | test_payments.py::test_amount_bounds (1e9 ok, 1000000001 -> 422) |
| R-4.24 **H** | §4 | "no operation produces a balance outside ±2⁵³. Monetary arithmetic must preserve exact minor-unit values without rounding error." | invariant | test_runtime.py::test_large_balance_exact (seed 9007199254740991 - 1e9, receive 1e9, /me exact) |
| R-4.25 **H** | §4 | "Seeded users must be able to log in with the given password immediately." | behaviour | test_reset.py::test_seeded_login_immediately |
| R-4.26 **H** | §4 | "`balance` is the wallet balance **after** every seeded payment has been applied. Seeded numbers are consistent; you do not replay seeded payments against balances." | behaviour | test_reset.py::test_seeded_payments_not_replayed (/me equals fixture balance) |
| R-4.27 **H** | §4 | "A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from `POST /_test/reset` and change nothing." | error | test_reset.py::test_negative_balance_422_state_unchanged (previous fixture still served, old token still valid) |
| R-4.28 | §4 | "`minor_units` is `0`, `2` or `3`. Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3)." | format | test_runtime.py::test_me_currency_from_fixture; test_reset.py::test_minor_units_invalid_422 (D-10) |
| R-4.29 | §4 | Fixture shape: users {id,email,password,display_name,handle,balance}, payments {id,from_user_id,to_user_id,amount,note,visibility}, requests {id,requester_id,payer_id,amount,note,status} | format | test_reset.py::test_seeded_payment_and_request_visible_with_fixture_ids |
| R-4.30 | §4 | "An administrative balance endpoint is out of scope." | operational | untestable: scope statement |

## 5. Errors

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-5.1 **H** | §5 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": ..., "message": ... } }`" | format | test_errors.py (helper `assert_error(resp, status, code)` asserts shape and `message` is a string, used by every error test) |
| R-5.2 | §5 | "Use the specified HTTP status and `code`. The human-readable `message` may use any wording." | format | as R-5.1 |
| R-5.3 | §5 | "400 \| `malformed_request` \| Unparseable body, or a field of the wrong JSON type" | error | test_errors.py::test_unparseable_body_400; test_errors.py::test_non_object_body_400; test_errors.py::test_wrong_type_handle_400 |
| R-5.4 | §5 | "400 \| `missing_idempotency_key` \| Required `Idempotency-Key` header absent or empty" | error | test_idempotency.py::test_missing_or_empty_key_400 (all five paths) |
| R-5.5 | §5 | "401 \| `unauthenticated` \| Missing, malformed or unknown bearer token" | error | test_auth.py::test_401_missing_malformed_unknown_token (every authenticated endpoint) |
| R-5.6 | §5 | "403 \| `forbidden` \| Authenticated, but not permitted to touch this resource" | error | test_requests.py::test_requester_cannot_pay_403; test_settlements.py::test_non_operator_403 |
| R-5.7 | §5 | "404 \| `not_found` \| No such resource, or not visible to this caller" | error | test_requests.py::test_unknown_request_404 (pay/decline/cancel); test_payments.py::test_unknown_handle_404_no_movement |
| R-5.8 | §5 | "409 \| `idempotency_key_reuse` \| Key already used by this caller with a different request body" | error | test_idempotency.py::test_same_key_different_body_409 |
| R-5.9 | §5 | "422 \| `validation_failed` \| A required field or query parameter is missing, or a stated rule is violated with no more specific code" | error | test_payments.py::test_missing_required_fields_422 (to_handle, amount); test_auth.py::test_signup_missing_fields_422 |
| R-5.10 **H** | §5 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error. This includes invalid dates, negative counts and values exceeding a stated maximum or length." | error | test_payments.py::test_amount_bounds; test_payments.py::test_note_length; test_payments.py::test_invalid_handle_format (422 or 404, D-04) |
| R-5.11 **H** | §5 | "invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`." | error | test_payments.py::test_amount_bool_or_string_422; test_payments.py::test_amount_null_422; test_payments.py::test_note_non_string_422 (null, 5, []); test_payments.py::test_visibility_invalid_422 (null, "PUBLIC", 1) |
| R-5.12 **H** | §5 | "Omission alone selects the optional-field defaults." | behaviour | test_payments.py::test_defaults_note_empty_visibility_public |
| R-5.13 **H** | §5 | "Other wrong JSON types follow the rule below." (i.e. 400) | error | test_errors.py::test_wrong_type_handle_400 (to_handle: 5); test_splits.py::test_participant_handles_not_array_400 |
| R-5.14 **H** | §5 | "An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value." | error | test_activity.py::test_query_int_non_decimal_422 (limit and offset × "1e9","4.0","+4","-0"," 4","abc","") ; same on GET /requests |
| R-5.15 | §5 | "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." | error | test_errors.py::test_valid_type_bad_value_never_400 |
| R-5.16 **H** | §5 | "`Idempotency-Key` \| 1 to 255 characters \| 422 `validation_failed`" | limit | test_idempotency.py::test_key_length_255_ok_256_422 |
| R-5.17 | §5 | "`limit` \| integer 1 to 200 \| 422 `validation_failed`" | limit | test_activity.py::test_limit_bounds (0, 1, 200, 201); test_requests.py::test_list_limit_bounds |
| R-5.18 | §5 | "`offset` \| integer 0 or more \| 422 `validation_failed`" | limit | test_activity.py::test_offset_bounds (-1, 0, large) |
| R-5.19 **H** | §5 | "Requests must not produce 5xx responses, including under concurrent load." | invariant | test_errors.py::test_hostile_bodies_no_5xx (invalid UTF-8, deep nesting, 1e400, 10**30, huge note, empty body); test_invariants.py::test_50_in_flight_no_5xx_within_timeout |

## 6. Authentication

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-6.1 | §6 | "POST /auth/signup { email, password, display_name } ->  201  { "user_id", "display_name", "token" }" | behaviour | test_auth.py::test_signup_201_shape_token_works |
| R-6.2 | §6 | "POST /auth/login { email, password } ->  200  { "user_id", "display_name", "token" }" | behaviour | test_auth.py::test_login_200_shape_token_works |
| R-6.3 | §6 | "Email already registered \| 409 `email_taken`" | error | test_auth.py::test_signup_email_taken_409 (seeded and signed-up emails) |
| R-6.4 **H** | §6 | "Password shorter than 8 characters \| 422 `validation_failed`" | error | test_auth.py::test_password_length_7_422_8_ok |
| R-6.5 | §6 | "`email` not of the form `local@domain` \| 422 `validation_failed`" | error | test_auth.py::test_email_format_422 ("ada", "@x.com", "ada@", "") (D-06) |
| R-6.6 | §6 | "Wrong password or unknown email on login \| 401 `unauthenticated`" | error | test_auth.py::test_login_wrong_password_or_unknown_email_401 |
| R-6.7 **H** | §6 | "The handle derived from the email (§4) is already taken \| 409 `handle_taken`, and no account is created" | error | test_auth.py::test_signup_handle_collision_409 (then login with that email -> 401; signup again with free handle succeeds) |
| R-6.8 | §6 | "Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above. Wallet API endpoints require authentication." | error | test_auth.py::test_401_missing_malformed_unknown_token |
| R-6.9 | §6 | "Authorization: Bearer <token>" | format | test_auth.py::test_401_missing_malformed_unknown_token ("Token x", "Bearer", "bearer-less raw token") |
| R-6.10 | §6 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." | behaviour | test_auth.py::test_multiple_tokens_all_valid (signup token + two logins all work) |
| R-6.11 **H** | §6 | "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent. Plaintext password storage is not permitted." | invariant | test_export_import.py::test_export_contains_no_plaintext_password (export must not contain "correct horse" nor a signup password); full proof: verifier code review |

## 7. Idempotency

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-7.1 | §7 | "Five write paths require an idempotency key (§8 and §11): `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits` and `POST /settlements`. Everything below applies to each of them independently." | behaviour | test_idempotency.py (every test parametrised over the five paths) |
| R-7.2 **H** | §7 | "The key is scoped to **the authenticated user**. Two different users may use the same key string with no interaction between them." | behaviour | test_idempotency.py::test_same_key_two_users_independent |
| R-7.3 | §7 | "A replay means the same user sending the **same method, the same path and the same body**." | behaviour | test_idempotency.py::test_replay_200_identical_body |
| R-7.4 **H** | §7 | "The same key with the same body on a different path is a different request, not a replay, and must succeed normally." | behaviour | test_idempotency.py::test_same_key_same_body_other_path_201 (/requests/A/pay vs /requests/B/pay with `{}`; /payments vs /requests) (D-03) |
| R-7.5 | §7 | "Header absent or empty \| 400 `missing_idempotency_key`" | error | test_idempotency.py::test_missing_or_empty_key_400 |
| R-7.6 | §7 | "First use of the key \| The normal response, **201**" | behaviour | test_idempotency.py::test_first_use_201 |
| R-7.7 **H** | §7 | "Replay: same key, same body \| **200**, body identical to the original response as a JSON value" | behaviour | test_idempotency.py::test_replay_200_identical_body (incl. created_at and ids; balances unchanged) |
| R-7.8 | §7 | "Same key, different body \| 409 `idempotency_key_reuse`" | error | test_idempotency.py::test_same_key_different_body_409 |
| R-7.9 **H** | §7 | "Key reused after the original request failed with 4xx \| Treated as a first use" | behaviour | test_idempotency.py::test_failed_4xx_key_reusable (409 insufficient then 201; 422 then 201 with a different body; 404 then 201) |
| R-7.10 **H** | §7 | "\"Same body\" means the same JSON value after parsing — key order and whitespace do not matter." | behaviour | test_idempotency.py::test_replay_key_order_whitespace_insensitive; test_idempotency.py::test_replay_1000_vs_1e3 (D-02) |
| R-7.11 **H** | §7 | "For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once." | invariant | test_idempotency.py::test_concurrent_identical_one_201_rest_200 (20 parallel, all five paths; balance moved once) |
| R-7.12 **H** | §7 | "A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes." | behaviour | test_idempotency.py::test_replay_after_cancel_returns_original_pending (POST /requests replay after cancel -> 200 status "pending"); test_idempotency.py::test_replay_after_balance_drop_still_200 |
| R-7.13 **H** | §7 | "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks. Thus changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`." | error | test_idempotency.py::test_claimed_key_beats_validation (amount -5 with used key -> 409 reuse); test_idempotency.py::test_replay_beats_resource_state (D-01) |

## 8. API

### GET /me

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.1 | §8 GET /me | `{ "user_id", "display_name", "handle", "balance", "currency", "minor_units" }` | format | test_runtime.py::test_me_shape_seeded |

### POST /payments

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.2 | §8 payments | "**An idempotent write path.** `Idempotency-Key` is required" | behaviour | test_idempotency.py (path = /payments) |
| R-8.3 | §8 payments | body `{ "to_handle", "amount", "note", "visibility" }` | format | test_payments.py::test_send_by_handle_201 |
| R-8.4 | §8 payments | "`note` is optional and defaults to `""`. `visibility` is optional and defaults to `"public"`." | behaviour | test_payments.py::test_defaults_note_empty_visibility_public |
| R-8.5 **H** | §8 payments | 201 body: payment_id, from_user_id, from_handle, to_user_id, to_handle, amount, currency, note, visibility, request_id (null), created_at — plus `settlement_id` null (§11) | format | test_payments.py::test_send_by_handle_201 (exact key set incl. settlement_id null, request_id null) |
| R-8.6 | §8 payments | "The caller's balance is below `amount` \| 409 `insufficient_funds`" | error | test_payments.py::test_insufficient_409_no_change; test_payments.py::test_exact_balance_ok_to_zero |
| R-8.7 | §8 payments | "`amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed`" | error | test_payments.py::test_amount_bounds (0, -1, 1, 1e9, 1000000001, 10.5, 1000.0000001) |
| R-8.8 | §8 payments | "`to_handle` is the caller's own handle \| 422 `self_payment`" | error | test_payments.py::test_self_payment_422 |
| R-8.9 **H** | §8 payments | "`note` longer than 200 characters \| 422 `validation_failed`" | error | test_payments.py::test_note_length (200 ok, 201 -> 422) (D-05) |
| R-8.10 | §8 payments | "`visibility` is neither `public` nor `private` \| 422 `validation_failed`" | error | test_payments.py::test_visibility_invalid_422 |
| R-8.11 | §8 payments | "No user has that handle \| 404 `not_found`" | error | test_payments.py::test_unknown_handle_404_no_movement |
| R-8.12 | §8 payments | "The debit and the credit are one atomic step. A payment is never visible in one wallet and not the other, and a failed payment leaves no trace in either." | invariant | test_payments.py::test_failed_payment_leaves_no_trace (balances + both feeds unchanged after each error); test_invariants.py::test_sum_conserved_concurrent_mixed_load |
| R-8.13 **H** | §8 payments | "`note` is stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and emoji survive a round trip byte for byte." | behaviour | test_payments.py::test_note_verbatim_roundtrip ("  <b>&amp;</b> \"q\" \\n 🍕👩‍👩‍👧 é vs é  " in response, feed of both parties, replay) |

### POST /requests

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.14 | §8 requests | "**An idempotent write path.**" | behaviour | test_idempotency.py (path = /requests) |
| R-8.15 | §8 requests | "The caller is the requester." | behaviour | test_requests.py::test_create_request_201 |
| R-8.16 | §8 requests | 201 body: request_id, requester_id, requester_handle, payer_id, payer_handle, amount, currency, note, status "pending", payment_id null, created_at | format | test_requests.py::test_create_request_201 (exact key set) |
| R-8.17 | §8 requests | "`amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed`" | error | test_requests.py::test_request_amount_bounds |
| R-8.18 | §8 requests | "`payer_handle` is the caller's own handle \| 422 `self_request`" | error | test_requests.py::test_self_request_422 |
| R-8.19 | §8 requests | "`note` longer than 200 characters \| 422 `validation_failed`" | error | test_requests.py::test_request_note_length |
| R-8.20 | §8 requests | "No user has that handle \| 404 `not_found`" | error | test_requests.py::test_request_unknown_payer_404 |
| R-8.21 **H** | §8 requests | "**The payer's balance is not checked here.** A request for more than the payer holds is created normally and sits `pending`." | behaviour | test_requests.py::test_request_above_payer_balance_201_pending (payer balance 0 and 1e9 request) |
| R-8.22 | §8 requests | (derived from §5) `note` optional, default `""`; non-string note 422 | behaviour | test_requests.py::test_request_note_default_and_type |

### POST /requests/{id}/pay

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.23 | §8 pay | "**An idempotent write path.** Only the payer may call it." | behaviour | test_idempotency.py (path = /requests/{id}/pay); test_requests.py::test_requester_cannot_pay_403 |
| R-8.24 | §8 pay | "The body carries `visibility` only, optional, default `"public"`. It is the payer's choice, not the requester's." | behaviour | test_requests.py::test_pay_default_public; test_requests.py::test_pay_visibility_private_sets_payment |
| R-8.25 **H** | §8 pay | "**A replay must send the identical body** — `{}` and `{"visibility": "public"}` are different JSON values, so reusing a key across the two is `409 idempotency_key_reuse`" | error | test_idempotency.py::test_pay_empty_vs_explicit_public_409 |
| R-8.26 | §8 pay | "Returns `201` with the created **payment**, exactly as `POST /payments` returns one, with `request_id` set to this request." | format | test_requests.py::test_pay_creates_payment_with_request_id (payer -> requester, amount = request amount) |
| R-8.27 | §8 pay | "The request becomes `paid` and carries the new `payment_id`." | behaviour | test_requests.py::test_pay_marks_request_paid_with_payment_id (via GET /requests for both parties) |
| R-8.28 | §8 pay | "The request is not `pending` \| 409 `request_not_pending`" | error | test_requests.py::test_pay_non_pending_409 (paid with new key, declined, cancelled) |
| R-8.29 | §8 pay | "The payer's balance is below `amount` \| 409 `insufficient_funds`" | error | test_requests.py::test_pay_short_409_then_funded_201 |
| R-8.30 | §8 pay | "The caller is not the request's payer \| 403 `forbidden`" | error | test_requests.py::test_requester_cannot_pay_403; test_requests.py::test_third_party_pay_403_or_404 (D-08) |
| R-8.31 | §8 pay | "Unknown request \| 404 `not_found`" | error | test_requests.py::test_unknown_request_404 |
| R-8.32 **H** | §8 pay | "Replaying a successful payment returns 200 with its original payment body, including when the request is already `paid`. It moves no additional money and must not return `409 request_not_pending`." | behaviour | test_idempotency.py::test_pay_replay_after_paid_200_no_money |
| R-8.33 **H** | §8 pay | (precedence, D-01) 404 unknown → 403 not payer → 409 `request_not_pending` → 409 `insufficient_funds` | error | test_requests.py::test_pay_precedence (paid request + payer now short -> request_not_pending; requester on paid request -> 403) |

### POST /requests/{id}/decline and /cancel

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.34 | §8 decline | "Only the payer. No idempotency key. Returns `200` with the request, `status: "declined"`." | behaviour | test_requests.py::test_decline_200_no_key_needed |
| R-8.35 **H** | §8 decline | "Declining an already-declined request is `200` with the current state — declining twice is not an error." | behaviour | test_requests.py::test_decline_twice_200 |
| R-8.36 | §8 decline | "A `paid` or `cancelled` request is `409 request_not_pending`. Not the payer is `403 forbidden`." | error | test_requests.py::test_decline_paid_or_cancelled_409; test_requests.py::test_requester_cannot_decline_403 |
| R-8.37 | §8 cancel | "Only the requester. No idempotency key. Returns `200` with the request, `status: "cancelled"`." | behaviour | test_requests.py::test_cancel_200_no_key_needed |
| R-8.38 **H** | §8 cancel | "Cancelling an already-cancelled request is `200`." | behaviour | test_requests.py::test_cancel_twice_200 |
| R-8.39 | §8 cancel | "A `paid` or `declined` request is `409 request_not_pending`. Not the requester is `403 forbidden`." | error | test_requests.py::test_cancel_paid_or_declined_409; test_requests.py::test_payer_cannot_cancel_403 |
| R-8.40 | §8 decline/cancel | (derived from §5) unknown request id → 404 `not_found`; ignores any body | error | test_requests.py::test_unknown_request_404 |

### GET /requests

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.41 | §8 list requests | "Requests where the caller is the requester or the payer, and no others." | invariant | test_requests.py::test_list_only_own_requests |
| R-8.42 | §8 list requests | "Newest first by `created_at`." | behaviour | test_requests.py::test_list_newest_first (created ≥1.1 s apart) |
| R-8.43 | §8 list requests | "`direction` is `incoming` (the caller is the payer), `outgoing` (the caller is the requester) or absent for both." | behaviour | test_requests.py::test_list_direction_filter |
| R-8.44 | §8 list requests | "`status` is one of the four statuses, or absent for all." | behaviour | test_requests.py::test_list_status_filter (all four) |
| R-8.45 | §8 list requests | "`limit` defaults to 50, range 1 to 200. `offset` defaults to 0 and must be 0 or more. Outside either range is 422 `validation_failed`." | limit | test_requests.py::test_list_limit_bounds; test_requests.py::test_list_default_limit_50 (60 requests -> 50 + has_more) |
| R-8.46 **H** | §8 list requests | "An unknown `direction` or `status` value is also 422." | error | test_requests.py::test_list_unknown_direction_status_422 ("INCOMING", "", "accepted") |
| R-8.47 **H** | §8 list requests | "`has_more` is true when items exist beyond the last one returned." | behaviour | test_requests.py::test_list_has_more_exact_boundary (n items: limit=n -> false; limit=n-1 -> true; offset=n -> [] false) |
| R-8.48 | §8 list requests | `{ "requests": [ ... ], "has_more": false }` | format | test_requests.py::test_list_shape |

### POST /splits

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.49 | §8 splits | "**An idempotent write path.** Splits an amount the caller already paid, and asks each of the other participants for their share by creating one `pending` request each." | behaviour | test_splits.py::test_split_example_3000_3; test_idempotency.py (path = /splits) |
| R-8.50 **H** | §8 splits | "The caller may be included in `participant_handles` or omitted." | behaviour | test_splits.py::test_caller_omitted_all_listed_get_requests (n = number listed, D-09) |
| R-8.51 | §8 splits | "Shares follow the equal-split rule in §9, in the order the handles are given." | behaviour | test_splits.py::test_shares_table_rows |
| R-8.52 | §8 splits | "**A request is created for every participant except the caller**, each for that participant's share, with the caller as requester." | behaviour | test_splits.py::test_split_example_3000_3 |
| R-8.53 | §8 splits | 201 body: split_id, amount, currency, note, shares [{handle, amount}], requests [request...], created_at | format | test_splits.py::test_split_example_3000_3 (exact shape) |
| R-8.54 | §8 splits | "`shares` covers every participant including the caller, in the order given, and always sums to `amount`. `requests` covers every participant except the caller, in the same order." | behaviour | test_splits.py::test_shares_and_requests_order (caller in middle position) |
| R-8.55 | §8 splits | "`amount` below 1, above 1000000000, or not an integer \| 422 `validation_failed`" | error | test_splits.py::test_split_amount_bounds |
| R-8.56 | §8 splits | "`participant_handles` empty, or containing a duplicate handle \| 422 `validation_failed`" | error | test_splits.py::test_participants_empty_or_duplicate_422 (duplicate caller too) |
| R-8.57 | §8 splits | "`note` longer than 200 characters \| 422 `validation_failed`" | error | test_splits.py::test_split_note_length |
| R-8.58 | §8 splits | "Any handle is unknown \| 404 `not_found`" | error | test_splits.py::test_unknown_participant_404_creates_nothing |
| R-8.59 **H** | §8 splits | "A split whose only participant is the caller is **valid**: it computes one share, creates zero requests, and returns `"requests": []`." | behaviour | test_splits.py::test_only_caller_valid_zero_requests |
| R-8.60 **H** | §8 splits | "Nothing about a split checks anyone's balance." | behaviour | test_splits.py::test_split_ignores_balances (caller and participants at 0) |

### GET /activity

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-8.61 | §8 activity | "Payments visible to the caller by the feed contract in §4, newest first by `created_at`." | behaviour | test_activity.py::test_feed_newest_first (≥1.1 s apart); test_activity.py::test_feed_contract_matrix |
| R-8.62 | §8 activity | `{ "payments": [ { ...payment... } ], "has_more": false }` | format | test_activity.py::test_feed_shape (items are full payment objects incl. settlement_id) |
| R-8.63 | §8 activity | "The relative order of two payments created within the same second is unspecified. Stable pagination during concurrent writes is not required for this endpoint." | behaviour | untestable: permission; tests never assert intra-second order |
| R-8.64 | §8 activity | "`limit` and `offset` behave exactly as in `GET /requests`." | limit | test_activity.py::test_limit_bounds; test_activity.py::test_offset_bounds; test_activity.py::test_has_more_boundary; test_activity.py::test_default_limit_50 |

## 9. Money and rounding

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-9.1 | §9 | "Shares must be whole minor units, sum exactly to `amount` and differ by at most one minor unit." | invariant | test_splits.py::test_share_properties_many_amounts (amount 1..50 × n 1..7) |
| R-9.2 | §9 | "When the amount does not divide evenly, the larger shares go to the first participants in `participant_handles` order." | behaviour | test_splits.py::test_shares_table_rows |
| R-9.3 | §9 | "1000 \| 3 \| 334, 333, 333" | behaviour | test_splits.py::test_shares_table_rows[1000-3] |
| R-9.4 **H** | §9 | "1 \| 3 \| 1, 0, 0" | behaviour | test_splits.py::test_shares_table_rows[1-3] |
| R-9.5 | §9 | "10 \| 3 \| 4, 3, 3" | behaviour | test_splits.py::test_shares_table_rows[10-3] |
| R-9.6 | §9 | "999 \| 3 \| 333, 333, 333" | behaviour | test_splits.py::test_shares_table_rows[999-3] |
| R-9.7 | §9 | "5 \| 5 \| 1, 1, 1, 1, 1" | behaviour | test_splits.py::test_shares_table_rows[5-5] |
| R-9.8 | §9 | "Splitting the same amount among the same people in a different `participant_handles` order gives the extra unit to a different person." | behaviour | test_splits.py::test_order_moves_extra_unit |
| R-9.9 **H** | §9 | "A share of `0` is legal and still produces a request for that participant." | behaviour | test_splits.py::test_zero_share_creates_request (amount 0 request, pending; paying it gives 201 amount 0) (D-11) |
| R-9.10 **H** | §9 | "Each split's shares are independent of previous splits." | behaviour | test_splits.py::test_no_carry_between_splits (split 1/3 twice -> both 1,0,0) |
| R-9.11 | §9 | "After any number of splits have been paid in full, wallet balances must still sum exactly to the seeded total." | invariant | test_invariants.py::test_sum_conserved_after_splits_paid |

## 10. Export and import

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-10.1 | §10 | "The service must support `GET /_test/export` and `POST /_test/import`. Like reset, these are unauthenticated test endpoints." | behaviour | test_export_import.py::test_export_import_unauthenticated |
| R-10.2 | §10 | "Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object)." | format | test_export_import.py::test_export_shape |
| R-10.3 | §10 | "The state format is opaque to the caller and must be accepted unchanged by import." | behaviour | test_export_import.py::test_roundtrip_unchanged_export_204 |
| R-10.4 | §10 | "Import takes that entire object and atomically replaces the service's state, returning 204." | behaviour | test_export_import.py::test_roundtrip_unchanged_export_204 |
| R-10.5 **H** | §10 | "No dependency on the source process, files, volume, port or network address is allowed." | operational | ops: export from container A, import into fresh container B, full post-import checks pass; in-suite proxy: test_export_import.py::test_import_after_reset_restores_everything |
| R-10.6 **H** | §10 | "Import is replacement, not merge; repeating it restores the exported state without duplicating anything." | behaviour | test_export_import.py::test_import_twice_no_duplicates (feed counts, request counts, balances identical) |
| R-10.7 | §10 | "Invalid JSON follows §5" | error | test_export_import.py::test_import_invalid_json_400 |
| R-10.8 **H** | §10 | "missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination." | error | test_export_import.py::test_import_rejects_and_keeps_state (missing state, track "other", format_version 2, state {} / state "x"; afterwards old tokens, balances and feed unchanged) (D-12) |
| R-10.9 | §10 | "Test control calls have a 10-second timeout." | limit | test_export_import.py::test_export_import_within_10s (after 500 payments) |
| R-10.10 **H** | §10 | "Export is an atomic, read-only snapshot; subsequent source writes do not change it." | behaviour | test_export_import.py::test_export_snapshot_isolation (export, write, compare saved export to the import result; export twice without writes -> identical states as JSON value) |
| R-10.11 **H** | §10 | "Preserve accounts and hashed-password login, existing bearer tokens, currency, balances, payments, requests, permissions" | behaviour | test_export_import.py::test_import_preserves_logins_tokens_balances_feed_requests_operators |
| R-10.12 **H** | §10 | "all completed idempotent request bodies and original responses" | behaviour | test_export_import.py::test_replay_after_import_200_same_body (all five paths); test_export_import.py::test_reuse_after_import_409 |
| R-10.13 **H** | §10 | "Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance." | invariant | test_export_import.py::test_ids_timestamps_balances_identical_after_import |
| R-10.14 **H** | §10 | "Failed request keys remain reusable." | behaviour | test_export_import.py::test_failed_key_reusable_after_import |
| R-10.15 **H** | §10 | "Existing receipts, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement." | behaviour | test_export_import.py::test_import_after_reset_restores_everything (export, reset to other fixture, import, old token + replay work) |
| R-10.16 **H** | §10 | "Import removes all previous destination data and credentials." | behaviour | test_export_import.py::test_import_removes_destination_users_and_tokens (user/token created after export -> 401 after import) |
| R-10.17 | §10 | "Reset clears all state, including imported state." | behaviour | test_export_import.py::test_reset_after_import_clears |
| R-10.18 | §10 | "Exports may contain credentials and session tokens; handle them as private test artifacts." / "State need not survive an abrupt container restart." | operational | untestable: handling guidance and a permission |
| R-10.19 **H** | §10 + §3.4 | (derived) IDs generated after import must not collide with imported IDs | invariant | test_export_import.py::test_new_ids_after_import_unique |

## 11. Atomic net settlements

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-11.1 | §11 | "The reset fixture may include `settlement_operator_ids`, an array of user ids, default []." | format | test_settlements.py::test_default_no_operators_403 |
| R-11.2 **H** | §11 | "An operator may execute a settlement across any wallets." | behaviour | test_settlements.py::test_operator_settles_between_third_parties (operator not party to any transfer) |
| R-11.3 **H** | §11 | "This permission does not grant access to another user's requests or private activity items." | invariant | test_settlements.py::test_operator_cannot_see_others_private_or_requests (feed excludes private members it is not party to; GET /requests excludes; pay/decline/cancel of others' requests -> 403/404) |
| R-11.4 | §11 | "`POST /settlements` requires an operator and an idempotency key. No token gives 401; authenticated non-operator gives 403 `forbidden`." | error | test_settlements.py::test_no_token_401; test_settlements.py::test_non_operator_403; test_idempotency.py (path = /settlements) |
| R-11.5 | §11 | body `{"transfers": [{"from_handle", "to_handle", "amount"}, ...]}` | format | test_settlements.py::test_operator_settlement_201 |
| R-11.6 **H** | §11 | "transfers contains 1..32 objects." | limit | test_settlements.py::test_transfer_count_bounds (0 -> 422, 1 ok, 32 ok, 33 -> 422) |
| R-11.7 **H** | §11 | "Each uses ordinary payment amount, note and visibility rules (defaults: empty note, public)." | behaviour | test_settlements.py::test_entry_amount_note_visibility_rules (amount 0/1e9+1/"5"/true, note 201 chars/null, visibility "x" -> 422; defaults applied; 1e3 accepted) |
| R-11.8 | §11 | "Unknown handle is 404; self-transfer is 422 `self_payment`; malformed batch shape is 422 `validation_failed`." | error | test_settlements.py::test_unknown_handle_404; test_settlements.py::test_self_transfer_422; test_settlements.py::test_malformed_shape_422 (transfers missing, not array, element not object) (D-13) |
| R-11.9 **H** | §11 | "Entry errors take precedence in input order, before insufficient funds." | error | test_settlements.py::test_entry_error_order ([self, unknown] -> self_payment; [unknown, self] -> 404; [unaffordable, bad amount] -> 422 not 409) |
| R-11.10 | §11 | "Unknown fields are ignored." | behaviour | test_settlements.py::test_unknown_fields_ignored |
| R-11.11 **H** | §11 | "A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative." | behaviour | test_settlements.py::test_net_affordability_chain (bob at 0: ada->bob 100, bob->cy 100 -> 201; order reversed also 201) |
| R-11.12 | §11 | "Insufficient collective funds gives 409 `insufficient_funds`." | error | test_settlements.py::test_collective_shortfall_409_nothing_moves |
| R-11.13 **H** | §11 | "Either all movements commit together or none do" | invariant | test_settlements.py::test_collective_shortfall_409_nothing_moves (no member payment in any feed, balances unchanged); test_settlements.py::test_concurrent_settlements_and_payments_sum_conserved |
| R-11.14 **H** | §11 | "failed validation claims no idempotency key and creates no payment or revision." | behaviour | test_settlements.py::test_failed_settlement_key_reusable (422 then 201 with corrected body, same key; 409 then 201) |
| R-11.15 | §11 | "Return 201 with `settlement_id`, `committed_at` and `payments` in input order." | format | test_settlements.py::test_operator_settlement_201 (order of payments matches transfers) |
| R-11.16 **H** | §11 | "Every member is an ordinary payment with `settlement_id` linking the batch; nonmembers expose null for that field." | format | test_settlements.py::test_member_settlement_id_and_nonmember_null (feed items, POST /payments, pay responses) |
| R-11.17 **H** | §11 | "Members have null request_id and the same server-assigned created_at, equal to committed_at." | format | test_settlements.py::test_members_share_created_at_equal_committed_at |
| R-11.18 | §11 | "Constituents follow ordinary activity-feed visibility." | behaviour | test_settlements.py::test_members_in_feed_by_contract |
| R-11.19 **H** | §11 | "The settlement response contains every member's receipt." | behaviour | test_settlements.py::test_response_includes_private_members (operator sees private members in its own response) |
| R-11.20 | §11 | "Replays return 200 with the original complete response. This is the fifth idempotent write path in stage 1." | behaviour | test_idempotency.py::test_replay_200_identical_body[settlements] |
| R-11.21 **H** | §11 | "A reset/import must preserve settlement operator permissions, original payments, requests, settlement membership and retry responses." | behaviour | test_export_import.py::test_import_preserves_settlements (operator still 201, members keep settlement_id, replay 200) |
| R-11.22 **H** | §11 | (derived, D-01) authorisation precedes body checks: 401 → 403 non-operator → 400 malformed → 400 missing key → key resolution → entry validation → 409 funds | error | test_settlements.py::test_non_operator_403_even_with_bad_body |
| R-11.23 | §11 + §1 | (derived) a settlement may involve the same wallet in several transfers; affordability is computed on the net per wallet | behaviour | test_settlements.py::test_repeated_wallet_netting |

## Cross-cutting precedence (derived, D-01)

| id | section | requirement (verbatim quote) | kind | proof |
|---|---|---|---|---|
| R-X.1 **H** | §5 + §7 | Evaluation order on idempotent writes: 401 → 400 `malformed_request` (body not a parseable JSON object) → 400 `missing_idempotency_key` → 422 key length → claimed key (200 replay / 409 reuse) → field validation (400 wrong type, 422 rules, 422 self_*) → 404 → 403 → 409 state → 409 funds | error | test_errors.py::test_precedence_matrix (only pairs the specification orders are asserted strictly; others accept either code) |
| R-X.2 **H** | §5 + §8 | Body-field validation precedes resource lookup: invalid amount with unknown handle → 422, not 404 | error | test_errors.py::test_validation_before_not_found |

## Coverage table

| section | rows | tested (HTTP suite) | ops (verifier, docker) | untestable (reason stated) | hidden (H) |
|---|---|---|---|---|---|
| §1 Scope | 11 | 9 | 0 | 2 | 0 |
| §2 Delivery | 12 | 2 | 9 | 1 | 1 |
| §3 Runtime | 13 | 11 | 2 | 0 | 5 |
| §4 Model | 30 | 29 | 0 | 1 | 11 |
| §5 Errors | 19 | 19 | 0 | 0 | 8 |
| §6 Auth | 11 | 11 | 0 | 0 | 3 |
| §7 Idempotency | 13 | 13 | 0 | 0 | 8 |
| §8 API | 64 | 63 | 0 | 1 | 14 |
| §9 Rounding | 11 | 11 | 0 | 0 | 3 |
| §10 Export/import | 19 | 17 | 1 | 1 | 11 |
| §11 Settlements | 23 | 23 | 0 | 0 | 13 |
| Cross-cutting | 2 | 2 | 0 | 0 | 2 |
| **Total** | **228** | **210** | **12** | **6** | **79** |

Untestable rows: R-1.4, R-1.11, R-2.11, R-4.30, R-8.63, R-10.18 (scope statements and
permissions). R-1.7's "transiently" clause is proven only indirectly (concurrent overspend
and crossing-payment probes). R-6.11 (hashing) is proven partially via export content and
fully only by code review. Recompute: `grep -c '^| R-' ledger.md` and
`grep -c '^| R-<section>\.' ledger.md`.

## Hidden requirements no sample check is likely to ask about

R-2.9 bcrypt cost vs 5 s / 10 s budgets · R-3.8 charset on errors · R-3.10 unknown fields cannot
spoof the sender · R-3.13/R-10.19 generated ids vs fixture/imported ids · R-4.3 `1000.0`/`1e3`
accepted · R-4.4 `true`/`"1000"` rejected · R-4.24 exact integers near 2⁵³ · R-4.26 seeded
payments not replayed · R-4.27 negative fixture balance leaves previous state intact ·
R-5.11 `note: null` → 422 · R-5.14 `+4`, `4.0`, `1e9` query integers → 422 · R-5.16 key length
256 → 422 · R-5.19 hostile bodies never 5xx · R-6.7 `handle_taken` creates no account ·
R-6.11 password hashing · R-7.4 same key on another path succeeds · R-7.9 failed-4xx key
reuse · R-7.10 key order/whitespace-insensitive body equality · R-7.12 replay after cancel
returns the original · R-7.13 claimed key resolved before validation · R-8.5 `settlement_id:
null` on every ordinary payment · R-8.13 note verbatim round trip · R-8.25 `{}` vs
`{"visibility":"public"}` · R-8.32 pay replay after paid · R-8.35/R-8.38 decline/cancel
twice · R-8.46 unknown direction/status → 422 · R-8.47 exact `has_more` boundary · R-8.59 caller-only
split · R-9.4/R-9.9 zero shares create requests · R-10.8 import atomic rejection · R-10.10
export snapshot isolation · R-10.12 replays survive import · R-10.16 import drops destination
tokens · R-11.9 settlement entry-error ordering · R-11.11 net affordability · R-11.14 failed
settlement claims no key · R-11.17 members share `created_at` = `committed_at` · R-11.19
private members in the operator's receipt.

## Risk list — the five most likely to be built wrong

1. **R-7.13 / R-X.1 idempotency precedence and R-7.11 concurrency.** The claimed-key lookup
   must run after auth and JSON-object parsing but *before* field validation and resource
   checks, keyed by (user, method, path, key), with the body compared as a parsed JSON value;
   concurrent identical requests must serialise on the key (one 201, rest 200 with the same
   body) while 4xx outcomes release the key. Builders usually validate first or store keys
   per (user, key) only.
2. **R-1.7 / R-1.8 / R-11.13 atomicity under 50 in-flight requests.** Check-then-write races
   on balance and request status (pay vs pay, pay vs cancel, settlement vs payment). One
   serialisation point (single writer lock or DB transaction with row locks) is needed;
   anything else will overdraw or double-pay under the concurrency tests.
3. **R-10.10–R-10.16 export/import fidelity.** The export must carry password hashes, tokens,
   idempotency records (bodies + original responses, successful only), timestamps, operator
   ids, settlement membership and the id counter; import must validate the whole state before
   swapping it in and must reject without side effects. A builder that re-seeds through the
   reset path regenerates ids/timestamps and loses tokens and receipts.
4. **R-4.3 / R-4.4 / R-5.11 / R-5.13 / R-5.14 type and number handling.** `1e3` and `1000.0`
   valid, `1000.5`, `true`, `"1000"`, `null` → 422 (not 400) for amount; wrong-typed handles
   → 400; query integers must be pure digit strings. Most JSON frameworks coerce or reject
   these the wrong way by default (e.g. Python `bool` is an `int`; pydantic coerces `"1000"`).
5. **R-11.9 / R-11.11 / R-11.17 settlement semantics.** Entry errors resolved in input order
   with a fixed in-entry order, *before* the collective funds check; affordability on net
   per-wallet balance (not sequential application); all members share one `created_at` equal
   to `committed_at`; every ordinary payment exposes `settlement_id: null`.

Runner-up: R-2.9 — bcrypt/argon2 at default cost on 2 vCPU makes a reset with many seeded
users exceed 10 s and 50 concurrent logins exceed 5 s; hash cost must be tuned (and seeded
hashing kept within the reset budget).
