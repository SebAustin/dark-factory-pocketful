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

## Early signals

- Event checker run 1 (analyst, isolated, rev 5619099): stage 1 pass 147/147, "claimed stage: 1". Own acceptance suite still red on crash/hidden findings (S1.11, S1.14, S1.15).

- Acceptance re-run (analyst, image from 76515c2 incl. 2e25cdb; test change 6a73e1f per L3): 422 passed, 0 failed, 3 skipped (docker-only). Event checker run 2 (rev 6a73e1f): 147/147, claimed stage 1.

## Plan gate

Round 1 (analyst, 22:3x): PLAN FINDINGS 1-6 against ledger 9bdc486. Lead decision L2: gate closed; findings converted to fix packet S1.11 (builder) or shown satisfied by verifier accepts on S1.6/S1.7.

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S1.1 | Skeleton | builder | 21:24 | yes | REJECT 0fa1f0b, ACCEPT 58c09cc |
| S1.2 | Auth | builder | 21:33 | yes | ACCEPT dfd7dc3 |
| S1.3 | Idempotency, payments, activity | builder | 21:33 | yes | REJECT 7e7c5c1, ACCEPT 38bd922 |
| S1.4 | Requests | builder | 21:40 | yes | ACCEPT 9407192 |
| S1.5 | Splits | designer | 21:55 | yes | ACCEPT 8f88f60 |
| S1.6 | Settlements | designer | 21:33 | yes | ACCEPT 0b87d7f |
| S1.7 | Export/import | designer | 21:45 | yes | REJECT 52bf3ed, ACCEPT af5270c |
| S1.12 | Import timestamp validation | designer | 22:4x | yes | ACCEPT 2b73788 |
| S1.15 | Import huge-number guard | designer | 22:5x | yes | ACCEPT 97a2879 |
| S1.11+S1.14 | Crash probes, numbers, lock scope, RUN.md, hidden-sweep fixes | builder | 22:3x | yes | ACCEPT 2e25cdb |
| S1.13 | Bound hashing concurrency | designer | 22:4x | yes | REJECT 5ff293a, ACCEPT 25fc824 |
| S1.8 | Load and limits | builder | 21:24 (plan) | yes | ACCEPT ef350b3 |

## Rejections and what they caught

- S1.13 @5ff293a REJECT (verifier): the semaphore(1) fix for CPU throttling serialised all scrypt; a 50-signup / 50-login burst then took up to 5.9 s (9-14 calls > 5 s) vs 3.9 s before — §2 5 s per-request timeout.

- S1.1 @0fa1f0b REJECT (verifier): HEAD/OPTIONS returned 501 text/html and a malformed request line returned stdlib HTML 400 — violates §5 envelope and no-5xx. Note promoted by lead: 1 MiB body cap would break large fixtures/imports (§3.3, §10).
- S1.3 @7e7c5c1 REJECT (verifier): GET /activity sorted created_at as strings; a +02:00 seeded timestamp ordered wrongly vs a +00:00 one (§8 newest first, §3.4 explicit offsets). Fix generalised by lead to every list and to fixture timestamp validation.
- S1.7 @52bf3ed REJECT (verifier): export after a legal zero-share split (§9) was refused by import with 422 (§10 'must accept an unchanged export'). Lead widened fix to a round-trip test after every kind of write.

## Stage gate

- Gate packet sent on 9d7ab5e (spec pasted 4 parts + packet); all seats told to stop containers for a quiet host.

## Gate table at acceptance

Stage 1 ACCEPTED at 9d7ab5e76ada506165f010ef4e751b746ffef108 (verdict reviews/stage1/GATE-9d7ab5e.md, commit 4fbeae9).

| Gate | Result | Evidence |
|---|---|---|
| G1 Ledger | green | 228 rows, 0 blank cells; 210 tested + 12 ops + 6 untestable with reasons; 0 ids unaccounted |
| G2 Plan | green | plan.md + lead decision L2 (one critique round, findings converted to S1.11 / shown by ACCEPTs) |
| G3 Acceptance | green | pytest stage-1/acceptance: 422 passed, 3 skipped, 0 failed; ACCEPTANCE_DOCKER=1 test_operational 4 passed (incl. no-outbound network) |
| G4 Chain | n/a | first stage |
| G5 Supplied checker | green | harness --stage 1 --mode isolated --out checks/s1-gate-verifier-174743: "stage 1: pass", "highest contiguous stage: 1", "claimed stage: 1 on the shipped checks" (stage 2 fail expected) |
| G6 Invariants | green | stress.py 60 s 8/8, 19615 reqs, 0 5xx; soak 15591 reqs, max <= 2.07 s, nr_throttled 0/1240; big: reset 2000 users 1.56 s, export/import 0.09/0.14 s; burst_auth max 1.10 s; 32 MiB |
| G7 Review | green | standards + spec, incl. 7a9d1cf and 6a73e1f; no plaintext passwords; RUN.md single command; no runtime network |
| G8 User facing | n/a | HTTP only |

## Wall time

Dispatch 21:22:12Z -> gate ACCEPT 22:51Z: about 1 h 29 min. Items: 17 work items (incl. ledger, plan, acceptance, stress tool, 3 diagnoses); 4 item rejections (0fa1f0b, 7e7c5c1, 52bf3ed, 5ff293a), 0 stage-gate failures; F4-F6 were findings attached to the S1.12 ACCEPT, not a rejection.

## Findings caught beyond item reviews

- Analyst acceptance suite (S1.A) and hidden sweep (S1.AH) caught defects every item review had passed: deep-nesting segfault (exit 139), huge-exponent amount wedging the service under the lock, 5000-digit ints -> 400 not 422, lone surrogates committing a payment then dropping the connection and poisoning /activity for all users, trailing-newline regex bypasses, huge exponent in unknown fields and in import. All fixed in 2e25cdb / 97a2879.
- Designer soak (S1.9) caught CFS CPU throttling from concurrent scrypt (calls up to 8.2 s); fixed in 25fc824 after one rejection for over-serialising (S1.13 F7).
- Event checker (isolated) passed 147/147 throughout; it did not reach any of the above.

## Decisions

- L1 build before plan gate closed; L2 plan gate closed after one round; L3 5000-digit offset is valid (200 empty page). Details in runlog/state.md.

## Open risks

- scrypt cost lowered to N=2^13 (signup) and 2^9 (seeded) for the 2 vCPU / 5 s budget; spec sets no floor.
- Equal seeded passwords share one salt (plan D7).
- Latency on a heavily loaded host: client-side maxima up to ~10 s were measured only when host load was 14-18 on 10 CPUs (D-20); server-side handler time stayed < 0.75 s.
- A refused settlement consumes an id counter value (not observable).
