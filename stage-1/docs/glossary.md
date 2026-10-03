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
