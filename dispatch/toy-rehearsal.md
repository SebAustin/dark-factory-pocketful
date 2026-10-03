@lead Rehearsal run on the practice track "toy". Build all four stages in order, one at a time, as a dark-factory run: do not ask me anything; resolve questions inside the band and report at the end.

PATHS (absolute; give these to every seat in every packet)
- Result repository: /Users/sebastienhenry/dark-factory/band-work/toy-result
- Specifications: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/toy/spec/stage-1.md through stage-4.md
- Event checker working directory: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs
- Python with pytest, httpx and playwright: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

TASK
Stage 1 goes in stage-1/. When stage 1 is accepted, copy the folder to stage-2/ (delete any nested .git), commit the copy, and extend it to the stage 2 specification; the same for stage-3/ and stage-4/. Each folder needs source, a Dockerfile and a RUN.md. Paste each specification in full into the packets that need it: seats cannot read this message. Preferred stack: Python 3.12 standard library on python:3.12-alpine, no network at run time.

GATES per stage, on one revision, run by the verifier:
- the analyst's acceptance suites for this and every earlier stage, green;
- the event checker must print "claimed stage: N":
  cd /Users/sebastienhenry/dark-factory/dark-factory-wearedevs && .venv/bin/python -m harness run --track toy --repo /Users/sebastienhenry/dark-factory/band-work/toy-result --stage N --out /Users/sebastienhenry/dark-factory/band-work/checks/toy-sN-<unique suffix>
- two-axis review.

DONE
Record runlog/stageN.md for each stage and post one final report in this room with each accepted revision.
