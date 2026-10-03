@lead Run stage 4 of the pocketful track as a dark-factory run. This message is the only human input for this stage: do not ask me anything; resolve questions inside the band and report at the end.

PATHS (absolute; give these to every seat in every packet)
- Result repository: /Users/sebastienhenry/dark-factory/band-work/result
- Start from the accepted folder: /Users/sebastienhenry/dark-factory/band-work/result/stage-3 (frozen: do not change it)
- Stage folder to create: /Users/sebastienhenry/dark-factory/band-work/result/stage-4
- Specification: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-4.md (earlier specifications still apply except where stage 4 changes them: same folder, stage-1.md to stage-3.md)
- Event checker working directory: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs
- Python with pytest, httpx and playwright: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

TASK
Copy stage-3 to stage-4 (delete any nested .git in the copy), commit the unchanged copy, then extend it to the stage 4 specification. Read the whole specification yourself, then paste it in full (numbered parts) into every packet that needs it, including the verifier's stage gate packet: seats cannot read this message.

ENGINEERING CONSTRAINTS
- The specification is the source of truth; the event ships only a small part of this stage's checks. Do not open or read the event's test directory (pocketful/test).
- Changes to many existing records apply atomically: all of them or none, under concurrent writes, and history written by earlier stages stays truthful.
- State created by earlier stages and imported from earlier exports must keep working (populated-state upgrades are judged).
- Every behaviour and screen from stages 1 to 3 keeps working unless stage 4 changes it.

GATES (the verifier runs these on one revision before the stage is accepted)
- Stage 1 to 4 acceptance suites green against the stage-4 container.
- Event checker, isolated mode, must print "claimed stage: 4":
  cd /Users/sebastienhenry/dark-factory/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo /Users/sebastienhenry/dark-factory/band-work/result --stage 4 --mode isolated --out /Users/sebastienhenry/dark-factory/band-work/checks/s4-<unique suffix>
- Atomicity under concurrent writes with failure injected mid-batch; two-axis review.

DONE
Commit everything, record runlog/stage4.md, and post your final report in this room with the accepted revision.
