# Run state (lead's durable memory)

Track: pocketful. CURRENT STAGE: 2. Stage 2 dispatch: 2026-10-03T22:54:33Z.
Room: af150286-bfd0-4fd8-8ae1-c57d84bf2e91. Seats: henry.sebastien1982/{analyst,builder,designer,verifier}.
Spec copies: runlog/stage1-spec.md, runlog/stage2-spec.md.
Last accepted revision: 9d7ab5e76ada506165f010ef4e751b746ffef108 (stage 1). stage-1/ is FROZEN.

## Stage 2 phase

- [x] Carry forward 10e5b5e
- [x] Ledger f146c3b
- [x] Plans 0cfc980 / 624aa75
- [x] Plan gate: closed L6 after one round
- [ ] Work items split
- [ ] Item reviews
- [ ] Stage gate
- [ ] Run log recorded

## Stage 2 work items

| Id | Title | Owner | Paths | State | Last rev | Rejections |
|---|---|---|---|---|---|---|
| S2.0 | Carry forward copy | builder | stage-2/ (whole copy) | accepted | 10e5b5e | 0 |
| S2.V | Screen walker tooling | verifier | reviews/stage2/tools/ | done (375/390/1280) | 1275ada | 0 |
| S2.L | Ledger + glossary (182 new rows, D-21..D-38) | analyst | stage-2/docs/ledger.md, glossary.md | done | f146c3b | 0 |
| S2.8 | Upgrade keeps destination sessions (D-22 / L5) + ttl + pay replay | builder | transfer_io.py, store | accepted | bf2e57d | 0 |
| S2.P | API/model plan | builder | stage-2/docs/plan.md | built (to critique) | 0cfc980 | 0 |
| S2.U | UI plan | designer | stage-2/docs/ui-plan.md | built (to critique) | 624aa75 | 0 |
| S2.1 | HTML/static seam | builder | app/ web serving, Dockerfile | accepted | ea8913c | 0 |
| S2.2 | Holds model | builder | store, me, fixture | accepted | c0df3c8 | 0 |
| S2.3 | Authorize + list | builder | authorizations.py | accepted | 3facf62 | 0 |
| S2.4 | Capture + void | builder | authorizations.py, store | accepted | 3d926ec | 0 |
| S2.5 | Export/import migration | builder | transfer_io.py | accepted (+ eab708e accepted) | 4e4559c | 0 |
| S2.6 | Concurrency/load | builder | tests, tools | accepted | 0c72f1f | 0 |
| S2.7 | Import hold check + early checker signal | builder | transfer_io.py | (a) in review eab708e; (b) checker run on 3dbd491: stage 2 33/35, 2 UI fails -> S2.U9 | eab708e | 0 |
| S2.U9 | /signup,/login reachable while signed in | designer | web/** | accepted | 77250c4 | 0 |
| S2.U6 | Authorizations screen | designer | web/** | accepted | 3dbd491 | 0 |
| S2.U7 | Competing clients / uncertain / upgrade | designer | web/** | accepted | 46b6e6f | 0 |
| S2.PG | Plan gate | analyst | - | done: 1 blocking (D-22 -> L5) + 5 minor -> S2.8, S2.U10 (L6) | - | 0 |
| S2.A | Acceptance (stage1 carried 425 + stage2 264) | analyst | stage-2/acceptance/ | re-run on 79a7bf6: stage1 422/0/3, stage2 262/268 (4 = S2.8, 2 = refresh button -> S2.U10) | 29db0cd | 0 |
| S2.U10 | Plan-gate UI fixes (dirty key, split parse, list DOM, refresh enabled) | designer | web/** | rejected R1 (F4 lost click after edit; same root as S2.U11) | 74d83a5 | 1 |
| S2.U11 | Edit during in-flight submit loses next click (+ closes U10 F4) | designer | web/** | fix resubmitted (in review) | 8fda234 | 1 |
| S2.U1 | Shell, visual system, nav, auth screens | designer | web/** | accepted (F1/F2 closed in U2-U3 review) | 773f649 | 1 |
| S2.U2+U3 | Client core + wallet screen | designer | web/** | accepted (F3 closed; 0259400 nowrap included) | b0aae37 | 1 |
| S2.U4+U5 | Requests + split screens | designer | web/** | accepted | 1ef373b | 0 |

## Stage 2 decisions

- L6 (23:5x): plan gate closed after one round; analyst findings F1-F6 converted to S2.8 (builder) and S2.U10 (designer) or shown already done (F5 Vary accepted ef17a11; F2 375 px walked).
- L5 (23:4x): D-22 ruled as analyst recommends. Stage 2 'A browser signed in before that export/import upgrade must remain signed in afterwards' overrides stage 1 §10 'Import removes all previous destination ... credentials' for the upgrade path only: tokens in the export survive import; additionally a STAGE-1-format import keeps any destination token whose user (same id, email and handle) exists in the imported state. A stage-2-format import stays pure replacement (R-10.16 holds).
- L4 (23:0x): designer starts U1 and builder the S2.1 seam before the plan gate closes (as L1 in stage 1); critiques return as fix notes.

---

# STAGE 1 (accepted, archived below)


Track: pocketful. Current stage: 1. Dispatch: 2026-10-03T21:22:12Z.
Room: af150286-bfd0-4fd8-8ae1-c57d84bf2e91. Seats: henry.sebastien1982/{analyst,builder,designer,verifier}.
Spec copy (shared memory): runlog/stage1-spec.md (verbatim copy of pocketful/spec/stage-1.md).
Last accepted revision: 9d7ab5e76ada506165f010ef4e751b746ffef108 (stage 1, gate ACCEPT 22:51Z).

## Stage 1 phase

- [x] Ledger (analyst) 9bdc486
- [x] Plan (builder) 3fb74d0
- [x] Plan gate: closed by lead decision L2 after round 1
- [x] Work items split
- [x] Item reviews (all accepted; S1.17 7a9d1cf reviewed inside gate)
- [x] Stage gate: ACCEPT 9d7ab5e (reviews/stage1/GATE-9d7ab5e.md)
- [x] Run log recorded

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
