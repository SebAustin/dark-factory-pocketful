# Stage 4 run log: pocketful refunds and batch corrections

- Dispatch: 2026-10-04T11:57:36Z (one human message; no further human input)
- Specification: pocketful/spec/stage-4.md (verbatim copy in runlog/stage4-spec.md); stages 1-3 still apply
- Stage folder: stage-4/ (carried from stage-3 accepted at 36547b6; stage-1/2/3 frozen)

## Timeline

| Time (UTC) | Event |
|---|---|
| 11:57 | Dispatch received; seats present |
| 11:59 | S4.0 (+RUN.md) -> builder; spec + S4.L -> analyst, S4.P -> builder, S4.O -> designer; L10 recorded (snapshots exported in stage 4; stage-3 limitation) |

## Plan gate

Round 1 (analyst): PLAN PASS on 8ea5e3c (+a3d5879) and S4.1 95cde7e against ledger 200efad + L12; agrees no fault hook needed (black-box mid-batch failure tests in stage4/test_atomic.py); note prepare-then-apply forwarded to builder.

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S4.0 | Carry forward + RUN.md | builder | 11:59 | yes | ACCEPT 2cdac7b, ACCEPT bb32d6a |
| S4.1 | Refunds | builder | 12:0x | yes | ACCEPT 95cde7e |
| S4.2 | Correction batches | builder | 12:1x | yes | ACCEPT 4f6e16d |
| S4.4 | Populated stage-1/2/3 upgrades | builder | 12:1x | yes | ACCEPT 2b8d873 |

## Rejections and what they caught

- S4.3 @d1ffc66 REJECT (verifier): tokens surviving an import were exported as fully rendered frozen results, so export grew reads x window (379 MB in 13.2 s after 1000 reads; over the 10 s control timeout and 64 MiB import cap). Fix: export each retained generation once + recipes.

## Gate table at acceptance

| Gate | Result | Evidence |
|---|---|---|

## Wall time
