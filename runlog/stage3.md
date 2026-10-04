# Stage 3 run log: pocketful statements and payment corrections

- Dispatch: 2026-10-04T01:12:36Z (one human message; no further human input)
- Specification: pocketful/spec/stage-3.md (verbatim copy in runlog/stage3-spec.md); stage-1.md and stage-2.md still apply (runlog/stage1-spec.md, runlog/stage2-spec.md)
- Stage folder: stage-3/ (carried from stage-2 accepted at 6a3fd33; stage-1/ and stage-2/ frozen)

## Timeline

| Time (UTC) | Event |
|---|---|
| 01:12 | Dispatch received; seats present |
| 01:14 | S3.0 -> builder; stage 3 spec (2 parts) + S3.L ledger -> analyst, S3.P plan -> builder, S3.O reference model -> designer |
| 01:16 | S3.0 committed 1a674f4; review + tooling -> verifier |

## Plan gate

Round 1 (analyst): plan agrees with D-41..D-60 except snapshot invalidation on import (finding 1) -> lead revised L8: snapshots cleared only by reset. Gate closed (L9).

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S3.0 | Carry forward | builder | 01:14 | yes | ACCEPT 1a674f4 |
| S3.1 | Bitemporal foundation | builder | 01:2x | yes | ACCEPT aa3922c |
| S3.2 | /me as_of/known_at | builder | 01:3x | yes | ACCEPT e02f93d |
| S3.3 | Statement + snapshots | builder | 01:3x | yes | REJECT fe6ff39, ACCEPT c8943d4 |
| S3.7 | Gate F7 RUN.md + F8 dead code | builder | 02:1x | yes (in re-gate) | ACCEPT 30821c2 via GATE-36547b6 |
| S3.4 | Corrections + revisions | builder | 01:3x | yes | ACCEPT 6757ba3 |
| S3.5 | Populated upgrade checks | builder | 01:3x | yes | ACCEPT 41cf24c |
| S3.6 | Ledger stress | builder | 01:3x | yes | ACCEPT c03a99e |

## Rejections and what they caught

- Stage gate @aaf1ee2 REJECT: stale RUN.md (again) and dead code. Lesson: carry-forward must include a RUN.md item in every stage.

- S3.3 @fe6ff39 REJECT (verifier): each statement read stored the whole window until reset — 5500 reads made a 69 MB export that import refused (>64 MiB) and memory grew ~67 KB/read toward the 2 GiB limit. Fix: O(1) snapshot recipes over append-only revisions, with generation references; snapshots not exported (final L8).

## Stage gate

- Gate packet sent on aaf1ee2db56a74f01e6db9f96b51fe34536e4bf6 (stage 3 spec pasted 2 parts + packet); seats told to quiet host.

- Gate 1 on aaf1ee2: REJECT (verifier) on G7 only — F7 stage-3/RUN.md was the stage-2 copy (same defect as stage 2 F6; lead process gap: RUN.md not in any item packet after carry-forward), F8 two dead functions. G1-G6, G8 green.

## Gate table at acceptance

Stage 3 ACCEPTED at 36547b6451dab2843338683d4226b7fbc1349250 (re-gate; verdict reviews/stage3/GATE-36547b6.md, commit 7c5a2d5). First gate attempt aaf1ee2 rejected on G7 only (stale RUN.md, dead code).

| Gate | Result | Evidence |
|---|---|---|
| G1 Ledger | green | 128 R3 rows + changed rows, 0 blank cells; decisions D-41..D-61; all 89 cited tests exist |
| G2 Plan | green | plan.md; analyst round 1; lead L7, L8 (revised), L9 |
| G3 Acceptance (stage 3) | green | acceptance/stage3: 134 passed |
| G4 Chain (stages 1, 2) | green | stage1 422 passed, 3 skipped; ACCEPTANCE_DOCKER 4 passed; stage2 API+UI 272 passed (gate 1), API 132 re-run; walker 390/1280 92/92 |
| G5 Supplied checker | green | checks/s3-gate2-verifier-212454: stage 2 pass, stage 3 pass, "claimed stage: 3 on the shipped checks" (stage 4 fail expected) |
| G6 Invariants | green | hist_probe 30 s 12249 writes interleaved with historical reads, one winner per race, 0 5xx; ledger_stress 60 s 4134 races; reference-model diff_run normal/--upgrade 1/--upgrade 2: 0 divergences; holds_stress, stress.py 8/8, soak; snapshot memory flat |
| G7 Review | green | standards + spec; upgrade_driver on populated stage-1/2 exports 26/0; both RUN.md commands start stage 3; no runtime network |
| G8 User facing | green | stage-3/web identical to stage-2/web; stage-2 screens re-walked clean |

## Wall time

Dispatch 01:12:36Z -> re-gate ACCEPT ~02:26Z: about 1 h 14 min. Item rejections: 1 (S3.3 fe6ff39, snapshot memory/export growth). Stage gate failures: 1 of 3 (aaf1ee2: stale RUN.md + dead code).

## Findings caught beyond item reviews

- Analyst plan gate: snapshots must survive imports (only reset ends them) -> L8 revised.
- Analyst suite + designer reference model (two independent spec-derived models) agreed with the service everywhere once landed; one designer divergence was a fixture error in the tool, withdrawn after lead challenge.
- Verifier: snapshot storage grew linearly (export 69 MB, ~67 KB/read) -> recipe snapshots.

## Decisions

- L7 build before plan gate; L8 (revised) snapshots in-process, survive imports, only reset ends them, not exported, no cap; L9 plan gate closed after one round. Analyst decision records D-41..D-61 cover every open time choice (µs monotonic clock, instant parsing, read instant, openings, correction error order, overdraft boundaries, snapshot freezing, hold intervals, upgrade rules).

## Open risks

- Live snapshots retain replaced states across imports until reset (~27 MB per 20k-payment state); ~70 such imports between resets would approach 2 GiB.
- created_at now renders with microseconds for new payments (D-41); stored/replayed earlier bodies unchanged.
- Voided stage-2 holds have no void time in a stage-2 export; closed at last capture or created_at (D-52).
- Process: RUN.md went stale after carry-forward in stages 2 and 3; every future stage gets a RUN.md item.
