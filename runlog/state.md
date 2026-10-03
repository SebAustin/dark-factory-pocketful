# Run state (lead's durable memory)

Track: pocketful. Current stage: 1. Dispatch: 2026-10-03T21:22:12Z.
Room: af150286-bfd0-4fd8-8ae1-c57d84bf2e91. Seats: henry.sebastien1982/{analyst,builder,designer,verifier}.
Spec copy (shared memory): runlog/stage1-spec.md (verbatim copy of pocketful/spec/stage-1.md).
Last accepted revision: none (stage 1 is the first).

## Stage 1 phase

- [ ] Ledger (analyst) — packet S1.L sent
- [ ] Plan (builder) — packet S1.P sent
- [ ] Plan gate
- [ ] Work items split
- [ ] Item reviews
- [ ] Stage gate
- [ ] Run log recorded

## Work items

| Id | Title | Owner | Paths | State | Last rev | Rejections |
|---|---|---|---|---|---|---|
| S1.L | Ledger + glossary (228 reqs, D-01..D-17) | analyst | stage-1/docs/ledger.md, glossary.md, decisions/D-* | built | 9bdc486 | 0 |
| S1.P | Implementation plan | builder | stage-1/docs/plan.md | built, in plan gate (S1.PG -> analyst) | 3fb74d0 | 0 |
| S1.D0 | Stress tool | designer | stage-1/tools/stress.py, README.md | built (validated vs stub) | bb8918a | 0 |
| S1.1 | Skeleton | builder | server, routes, store, testctl, Dockerfile, RUN.md | fix resubmitted (in review) | 58c09cc | 1 |
| S1.2 | Auth | builder | auth.py, passwords.py | accepted 21:5x | dfd7dc3 | 0 |
| S1.3 | Idempotency + payments + activity | builder | idempotency.py, payments.py | rejected R1 (F2 created_at ordering by string) -> fix assigned | 7e7c5c1 | 1 |
| S1.4 | Requests | builder | requests_.py | accepted (F2 sort tracked under S1.3) | 9407192 | 0 |
| S1.5 | Splits | designer | splits.py, tests/test_splits.py | accepted | 8f88f60 | 0 |
| S1.6 | Settlements | designer | settlements.py, tests/test_settlements.py | accepted | 0b87d7f | 0 |
| S1.7 | Export/import | designer | transfer_io.py, tests/test_transfer_io.py | rejected R1 (F3 zero-share export not importable) -> fix assigned | 52bf3ed | 1 |
| S1.8 | Load and limits (builder delivered before re-plan; designer copy cancelled) | builder | tests/soak.py | in review | ef350b3 | 0 |
| S1.A | Acceptance suite | analyst | stage-1/acceptance/ | assigned | - | 0 |

## Open rejections

- S1.1 R1 @0fa1f0b: F1 non-JSON 501/400 for HEAD/OPTIONS/bad request line. Lead promoted note: MAX_BODY 1 MiB too small for reset/import.
- S1.7 R1 @52bf3ed: F3 import rejects export containing zero-amount request.
- S1.3 R1 @7e7c5c1: F2 activity sorted by created_at string, wrong with mixed offsets.

## Decisions

- L1 (21:33): builder starts S1.2/S1.3 and designer S1.6 before the plan gate closes, to keep lanes busy; plan-gate findings return as fix packets. Plan risk judged low (analyst's independent ledger decisions D-01..D-17 agree with plan D1-D7 on order, scoping, number handling).
