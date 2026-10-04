# Stage 1 glossary — Pocketful

Domain terms as the specification uses them. No implementation detail.

| term | meaning | not to be confused with |
|---|---|---|
| user | An account that can log in, holds exactly one wallet and has one handle. | handle (the public name), user_id (the opaque id) |
| user_id | Opaque string id of a user (≤64 chars), fixture-supplied for seeded users. | handle |
| handle | Public, unique, immutable recipient name matching `^[a-z0-9_]{1,20}$`; how users address each other. | display_name (free text, not unique), email |
| derived handle | The handle of a signed-up user: email local part, lowercased, non-`[a-z0-9_]` → `_`, truncated to 20. | a client-chosen handle (signup has no handle field) |
| display_name | Free-text name returned by signup, login and /me. | handle |
| seeded user | A user created by `POST /_test/reset` from the fixture, able to log in immediately. | signed-up user (created by `/auth/signup`, balance 0) |
| token | Bearer credential returned by signup/login; never expires; many per user. | password, idempotency key |
| wallet / balance | The single integer amount of minor units a user holds; never negative. | amount (a single movement) |
| currency | The one service-wide currency code declared by the fixture (EUR, JPY, BHD). | minor_units |
| minor units | The integer subdivision of the currency (`minor_units` 0, 2 or 3); every API amount counts these. | major units (€10.00 = 1000 minor units at 2) |
| amount | Integer count of minor units on one payment/request/split/transfer, 1..1 000 000 000 (shares may be 0). | balance |
| seeded total | Sum of fixture balances at the last reset; the sum of all balances must always equal it. | sum of payments |
| payment | An immediate, atomic movement from a sender's wallet to a receiver's wallet; carries visibility. Sent directly, created by paying a request, or a settlement member. | request (asks, moves nothing) |
| sender / receiver | The `from` and `to` users of a payment. | requester / payer |
| request | A pending ask for money: the requester will receive, the payer is asked. Moves money at most once, only when paid. | payment, split |
| requester | The user who created a request and will receive; the only one who may cancel. | payer |
| payer | The user asked to pay; the only one who may pay or decline, and who chooses the payment's visibility. | sender of an unrelated payment |
| status | Request lifecycle: `pending` → exactly one of `paid`, `declined`, `cancelled`; terminal states never change. | visibility |
| visibility | `public` or `private`, one value on a payment, chosen when money moves; requests have none. | status |
| activity feed | `GET /activity`: payments where visibility is public or the caller is sender/receiver; never requests, never splits. | request list (`GET /requests`) |
| request list | `GET /requests`: only requests where the caller is requester or payer, filterable by direction and status. | activity feed |
| direction | `incoming` (caller is payer) or `outgoing` (caller is requester) filter on the request list. | sender/receiver |
| split | A one-shot division of an amount the caller already paid into equal shares, creating one pending request per non-caller participant. Not a feed item. | settlement, request |
| participant | A handle listed in `participant_handles`; may include the caller. | requester |
| share | One participant's whole-minor-unit portion of a split; shares differ by ≤1, sum to amount, extra units go to the earliest participants; may be 0. | request amount (equal to the share for non-callers) |
| settlement | An operator-submitted batch of 1..32 transfers that commits all-or-nothing when every wallet's net result is non-negative. | split, a single payment |
| transfer | One entry of a settlement (`from_handle`, `to_handle`, `amount`, optional note/visibility); becomes a member payment. | request |
| settlement operator | A user listed in the fixture's `settlement_operator_ids`; may move money between any wallets via settlements, but sees no extra requests or private payments. | administrator (no admin endpoints exist) |
| member payment | A payment created by a settlement; carries `settlement_id`, null `request_id`, and `created_at` = the settlement's `committed_at`. | non-member payment (`settlement_id: null`) |
| net affordability | A settlement is affordable iff each wallet's balance after all its incoming and outgoing transfers is ≥ 0 (order of transfers irrelevant). | sequential affordability |
| idempotency key | Client string (1..255 chars) in `Idempotency-Key` on the five write paths, scoped per authenticated user (and per method + path). | token |
| replay | Same user, same method, same path, same JSON body value, same key → 200 with the original body, no new effect. | reuse (same key, different body → 409) |
| claimed key | A key whose first use succeeded (2xx); 4xx outcomes never claim a key. | used-and-failed key (reusable) |
| fixture | The JSON body of `POST /_test/reset` declaring currency, users, payments, requests, operators. | export (opaque full state incl. tokens and receipts) |
| reset | Replaces all state with a fixture; 204; invalidates everything earlier. | import |
| export | `GET /_test/export`: atomic read-only snapshot `{track, format_version, state}`. | fixture |
| import | `POST /_test/import`: atomic replacement of all state by an unchanged export; 204; tokens, receipts and ids survive. | reset, merge |
| error envelope | `{"error": {"code", "message"}}` on every 4xx/5xx. | |
| receipt | The original response body of a successful idempotent write, returned again on replay. | current state of the resource |

## Stage 2 additions

| term | meaning | not to be confused with |
|---|---|---|
| total | A wallet's money, equal to `balance`; the sum of all totals equals the seeded total. | available |
| held | Sum of the remaining amounts of a payer's open, unexpired authorizations. Moves no money. | captured amount |
| available | `total − held`; what the user can spend; never negative; the headline number in the UI. | total, balance (balance = total) |
| authorization | A payer's reservation of money for a receiver (`to` party), captured later; statuses `open`, `captured`, `voided`, `expired`. | request (asks; reserves nothing), payment (moves money) |
| hold | The reservation an open authorization places on the payer's wallet, for its remaining amount. | balance debit |
| capture | Receiver's action turning (part of) an open authorization into an ordinary payment carrying `authorization_id`. | request pay |
| final capture | A capture with `final` true (default): closes the authorization (`captured`) and releases any remainder. | non-final capture (keeps the remainder held, stays `open`) |
| remaining amount | `amount − captured_amount` while open; 0 once closed. Exposed as `remaining_amount`. | captured_amount (cumulative) |
| void | Payer's release of their own open hold; status `voided`; idempotent at 200. | cancel (requests), decline |
| expiry | An authorization whose `expires_at` ≤ now is `expired` and holds nothing, evaluated at read/write time. | void |
| authorization_ttl_seconds | Fixture-wide lifetime for API-created authorizations (default 600): `expires_at = created_at + ttl`. | seeded `expires_at` (absolute) |
| upgrade | Importing the stage-1 service's export into the stage-2 service while a browser stays open. | reset |
| uncertain outcome | A write whose response was lost (network error, abort, 5xx): shown as `pay-uncertain`, retried with the same key and body. | refusal (a 4xx, shown as `pay-error`) |
| latest refresh wins | Only the most recently issued read may update the wallet/feed display; older responses arriving later are discarded. | last response wins |
| formatted amount | Minor units shown as a decimal with exactly `minor_units` places, one space, the currency code (`100.00 EUR`, `1200 JPY`, `1.500 BHD`); no sign, no grouping. | raw minor units (`data-amount`) |
| decimal input | What a person types in an amount field (`15`, `15.5`, `15.00`), converted to minor units; more than `minor_units` places or nonnumeric is refused before any request. | API amount (integer minor units) |
| split preview | Client-side shares computed by the §9 rule before posting; must equal the server's shares. | split response `shares` |
| content negotiation | `/requests` and `/authorizations` return HTML for `Accept: text/html`, JSON otherwise. | separate UI routes |

## Stage 3 additions (time model)

All instants are compared as absolute points in time (UTC), never as strings; offsets only change the
rendering (D-42). Server-assigned instants have microsecond precision and strictly increase (D-41).

| term | meaning | not to be confused with |
|---|---|---|
| created_at | The instant a payment moved money: server-assigned for API payments (members: the settlement's committed_at; captures: the capture instant), supplied or reset time for seeded payments, carried for imported ones. Never changes, even after corrections. | effective_at of a later revision |
| revision | One immutable version of a payment's amount and effective time. Revision 1 is the original (`amount` as paid, `effective_at = recorded_at = created_at`, `reason ""`); each correction appends revision n+1. | the payment object (original, unchanged) |
| effective_at | When a revision's money is deemed to have taken effect; drives `as_of`, statement windows and ordering. Revision 1: created_at; corrections: supplied, ≤ now. | recorded_at |
| recorded_at | When the service learned a revision (server-assigned; revision 1 = created_at). Strictly increasing per payment. Drives `known_at` selection. | effective_at |
| selected revision | For a payment and a `known_at` K: its latest revision with `recorded_at ≤ K`; none → the payment contributes nothing. Without K: the latest revision known at the read instant. | latest revision overall |
| as_of (T) | Inclusive instant for `GET /me`: balance after every selected revision with `effective_at ≤ T`, before every later one. Echoed exactly as given. | statement `to` (exclusive) |
| known_at (K) | Knowledge cut-off for `GET /me` and `GET /statement`: only revisions recorded at or before K count (and only hold events known by K). Echoed exactly as given. | as_of |
| statement window [from, to) | Half-open: entries with selected `from ≤ effective_at < to`. `from` default: before the wallet opened; `to` default: the read instant. | as_of (inclusive) |
| opening balance (wallet) | What the wallet held before anything moved: seeded ending balance minus the net of the ORIGINAL (revision 1) seeded payments; 0 for signed-up users; for imported states: imported balance minus the net of all imported payments. Corrections never change it. | statement `opening_balance` (balance just before `from`) |
| opening_balance / closing_balance (statement) | The caller's balance immediately before `from` / immediately before `to`, under the selected revisions. | wallet opening balance |
| delta | A statement entry's signed effect on the caller: −amount if the caller sent it, +amount if received (selected amount; may be 0). | correction difference |
| boundary | One distinct instant at which money or holds change; all movements and hold events at that instant are applied together before the balance is judged. | a single payment |
| event time | The server-assigned instant of an authorization lifecycle event (creation, capture, void); expiry's event time is `expires_at`. | recorded_at of a payment revision |
| closed_at | An authorization's closing event time: null while open; final-capture instant, void instant, or `expires_at` for expiry. | expires_at of an open hold |
| historical view | The balances (and holds) computed for one pair (as_of, known_at). | the current wallet |
| historical_overdraft | Rejection of a correction that would make total or available negative at any past boundary under the latest known revisions. | insufficient_funds (current available) |
| linked payment | A settlement member or a capture; immutable to single-payment corrections (422 `linked_payment_immutable`). | request-pay payment (correctable) |
| snapshot | Opaque token minted by every first `GET /statement`; pages exactly that read's frozen result (window, resolved `to` and `known_at`, selected revisions, entries, balances). Valid until reset; kept in the process, not exported, untouched by import (D-50, L8(1)). | idempotency key |
| read instant | The single instant at which a read is evaluated (taken from the service's monotonic clock while the state is consistent); defines "now" for default `to`, default `known_at` and default `as_of`. | client clock |
