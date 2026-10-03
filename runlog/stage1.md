# Stage 1 run log: pocketful payments and settlements

- Dispatch: 2026-10-03T21:22:12Z (one human message; no further human input)
- Specification: pocketful/spec/stage-1.md (verbatim copy in runlog/stage1-spec.md)
- Stage folder: stage-1/

## Timeline

| Time (UTC) | Event |
|---|---|
| 21:22 | Dispatch received; seats confirmed present (analyst, builder, designer, verifier) |
| 21:24 | S1.L ledger -> analyst, S1.P plan -> builder (spec pasted, 4 parts + packet) |
| 21:25 | S1.D0 stress tool -> designer (spec pasted) |
| ~21:30 | S1.P plan committed 3fb74d0; S1.1 skeleton 0fa1f0b (builder sent to verifier); S1.D0 stress tool bb8918a; S1.L ledger 9bdc486 (228 reqs) |
| 21:33 | S1.PG plan gate -> analyst; S1.A acceptance -> analyst; S1.2+S1.3 -> builder; S1.6 -> designer (decision L1) |

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S1.1 | Skeleton | builder | 21:24 | | REJECT 0fa1f0b |
| S1.2 | Auth | builder | 21:33 | yes | ACCEPT dfd7dc3 |
| S1.3 | Idempotency, payments, activity | builder | 21:33 | | REJECT 7e7c5c1 |
| S1.4 | Requests | builder | 21:40 | yes | ACCEPT 9407192 |
| S1.5 | Splits | designer | 21:55 | yes | ACCEPT 8f88f60 |
| S1.6 | Settlements | designer | 21:33 | yes | ACCEPT 0b87d7f |
| S1.7 | Export/import | designer | 21:45 | | REJECT 52bf3ed |

## Rejections and what they caught

- S1.1 @0fa1f0b REJECT (verifier): HEAD/OPTIONS returned 501 text/html and a malformed request line returned stdlib HTML 400 — violates §5 envelope and no-5xx. Note promoted by lead: 1 MiB body cap would break large fixtures/imports (§3.3, §10).
- S1.3 @7e7c5c1 REJECT (verifier): GET /activity sorted created_at as strings; a +02:00 seeded timestamp ordered wrongly vs a +00:00 one (§8 newest first, §3.4 explicit offsets). Fix generalised by lead to every list and to fixture timestamp validation.
- S1.7 @52bf3ed REJECT (verifier): export after a legal zero-share split (§9) was refused by import with 422 (§10 'must accept an unchanged export'). Lead widened fix to a round-trip test after every kind of write.

## Gate table at acceptance

| Gate | Result | Evidence |
|---|---|---|

## Wall time
