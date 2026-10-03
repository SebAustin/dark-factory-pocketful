@lead Run stage 3 of the pocketful track as a dark-factory run. This message is the only human input for this stage: do not ask me anything; resolve questions inside the band and report at the end.

PATHS (absolute; give these to every seat in every packet)
- Result repository: /Users/sebastienhenry/dark-factory/band-work/result
- Start from the accepted folder: /Users/sebastienhenry/dark-factory/band-work/result/stage-2 (frozen: do not change it)
- Stage folder to create: /Users/sebastienhenry/dark-factory/band-work/result/stage-3
- Specification: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-3.md (earlier specifications still apply except where stage 3 changes them: same folder, stage-1.md and stage-2.md)
- Event checker working directory: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs
- Python with pytest, httpx and playwright: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

TASK
Copy stage-2 to stage-3 (delete any nested .git in the copy), commit the unchanged copy, then extend it to the stage 3 specification. Read the whole specification yourself, then paste it in full (numbered parts) into every packet that needs it, including the verifier's stage gate packet: seats cannot read this message.

ENGINEERING CONSTRAINTS
- The specification is the source of truth. The event ships only a small part of this stage's checks, so the analyst's ledger and acceptance suite are what protect the stage: give the ledger the most time. Do not open or read the event's test directory (pocketful/test).
- Time matters in this stage: be precise about which instant each record carries and how queries as of an instant, corrections and pagination snapshots behave. Write decision records for every choice the text leaves open.
- State created by earlier stages, and state imported from an earlier stage's export, must keep working (upgrades over populated state are judged).
- Every stage 1 and stage 2 behaviour and screen keeps working unless stage 3 changes it. @designer surfaces any new user-visible history in the existing screens where the specification asks for it, and otherwise supports review.

GATES (the verifier runs these on one revision before the stage is accepted)
- Stage 1, 2 and 3 acceptance suites green against the stage-3 container.
- Event checker, isolated mode, must print "claimed stage: 3" (the stage 4 line it prints afterwards is expected to fail):
  cd /Users/sebastienhenry/dark-factory/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo /Users/sebastienhenry/dark-factory/band-work/result --stage 3 --mode isolated --out /Users/sebastienhenry/dark-factory/band-work/checks/s3-<unique suffix>
- Concurrent writes interleaved with historical reads; two-axis review.

DONE
Commit everything, record runlog/stage3.md, and post your final report in this room with the accepted revision.
