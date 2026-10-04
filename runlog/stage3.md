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

| Gate | Result | Evidence |
|---|---|---|

## Wall time
