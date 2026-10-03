# Run state (lead's durable memory)

Track: pocketful. Current stage: 1. Dispatch: 2026-10-03T21:22:12Z.
Room: af150286-bfd0-4fd8-8ae1-c57d84bf2e91. Seats: henry.sebastien1982/{analyst,builder,designer,verifier}.
Spec copy (shared memory): runlog/stage1-spec.md (verbatim copy of pocketful/spec/stage-1.md).
Last accepted revision: none (stage 1 is the first).

## Stage 1 phase

- [x] Ledger (analyst) 9bdc486
- [x] Plan (builder) 3fb74d0
- [x] Plan gate: closed by lead decision L2 after round 1
- [x] Work items split
- [x] Item reviews (all accepted; S1.17 7a9d1cf reviewed inside gate)
- [ ] Stage gate: packet sent on 9d7ab5e (seats told to quiet host)
- [ ] Run log recorded

## Work items

| Id | Title | Owner | Paths | State | Last rev | Rejections |
|---|---|---|---|---|---|---|
| S1.L | Ledger + glossary (228 reqs, D-01..D-17) | analyst | stage-1/docs/ledger.md, glossary.md, decisions/D-* | built | 9bdc486 | 0 |
| S1.P | Implementation plan | builder | stage-1/docs/plan.md | built, in plan gate (S1.PG -> analyst) | 3fb74d0 | 0 |
| S1.D0 | Stress tool | designer | stage-1/tools/stress.py, README.md | built (validated vs stub) | bb8918a | 0 |
| S1.1 | Skeleton | builder | server, routes, store, testctl, Dockerfile, RUN.md | accepted (58c09cc; 38bd922 body-cap change rides with S1.3-R1 review) | 58c09cc | 1 |
| S1.2 | Auth | builder | auth.py, passwords.py | accepted 21:5x | dfd7dc3 | 0 |
| S1.3 | Idempotency + payments + activity | builder | idempotency.py, payments.py | accepted | 38bd922 | 1 |
| S1.4 | Requests | builder | requests_.py | accepted (F2 sort tracked under S1.3) | 9407192 | 0 |
| S1.5 | Splits | designer | splits.py, tests/test_splits.py | accepted | 8f88f60 | 0 |
| S1.6 | Settlements | designer | settlements.py, tests/test_settlements.py | accepted | 0b87d7f | 0 |
| S1.7 | Export/import | designer | transfer_io.py, tests/test_transfer_io.py | accepted | af5270c | 1 |
| S1.8 | Load and limits (builder delivered before re-plan; designer copy cancelled) | builder | tests/soak.py | accepted | ef350b3 | 0 |
| S1.9 | Diagnose >5 s tail under auth-heavy load | designer | tools/soak.py, D-19 | done: CFS throttling by parallel scrypt | 3c8ac32 | 0 |
| S1.13 | Bound hashing concurrency (semaphore 1) | designer (passwords.py moved for this item) | app/passwords.py, tests/test_passwords_concurrency.py | accepted | 25fc824 | 1 |
| S1.10 | Early event-checker signal (moved to analyst) | analyst | findings only | run 1 PASS 147/147 claimed stage 1 on 5619099; re-run after S1.11/S1.14 | 5619099 | 0 |
| S1.A | Acceptance suite (400 tests) | analyst | stage-1/acceptance/ | built; 385/400 on c19a2b7, failures -> S1.11 | 1a37936 | 0 |
| S1.11 | Crash probes, numbers, lock scope, RUN.md | builder | validation, http_util, routes, store, server, RUN.md | accepted | 2e25cdb | 0 |
| S1.12 | Import timestamp validation | designer | transfer_io.py | accepted | 2b73788 | 0 |
| S1.AH | Hidden-requirement sweep (73/79 confirmed) | analyst | stage-1/acceptance/ | done | 2200e4a | 0 |
| S1.14 | Hidden-sweep fixes H1-H4 (regex \n, long query int, surrogates, exponent in canonical) | builder | validation, http_util, server, auth | accepted | 2e25cdb | 0 |
| S1.15 | Import huge-number guard | designer | transfer_io.py | accepted | 97a2879 | 0 |
| S1.16 | Residual spike diagnosis | designer | D-20 | done: host contention + client saturation; server max hold 4.2 ms; no app change | 25fc824 | 0 |
| S1.17 | Lowercase t/z RFC 3339 (verifier note) | builder | store.py | built (review at gate) | 7a9d1cf | 0 |

## Open rejections

(all S1.1-S1.8 rejections closed by 22:2x)

- S1.1 R1 @0fa1f0b: F1 non-JSON 501/400 for HEAD/OPTIONS/bad request line. Lead promoted note: MAX_BODY 1 MiB too small for reset/import.
- S1.7 R1 @52bf3ed: F3 import rejects export containing zero-amount request.
- S1.3 R1 @7e7c5c1: F2 activity sorted by created_at string, wrong with mixed offsets.

## Decisions

- L3 (23:0x): huge `offset` (e.g. 5000 digits) is VALID: §5 shared ranges give offset 'integer 0 or more' with no maximum, and §5 makes out-of-range 422 only for 'values exceeding a stated maximum'. Answer 200 with an empty list and has_more false; never 5xx. `limit` stays 1..200 -> 422. Analyst flips the two offset acceptance cases.

- L2 (22:3x): plan gate (G2) closed after one critique round. Analyst found 6 plan findings; code already existed, so each became a fix packet or was shown already satisfied by a verifier ACCEPT: P1,P2,P5,P6 -> S1.11 builder; P3 proven by S1.7 snapshot isolation probe; P4 proven by S1.6 precedence probes. Why: re-planning written code wastes a round; findings are fully covered by fix packets with DONE WHEN.

- L1 (21:33): builder starts S1.2/S1.3 and designer S1.6 before the plan gate closes, to keep lanes busy; plan-gate findings return as fix packets. Plan risk judged low (analyst's independent ledger decisions D-01..D-17 agree with plan D1-D7 on order, scoping, number handling).
