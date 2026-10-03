@lead Run stage 1 of the pocketful track as a dark-factory run. This message is the only human input for this stage: do not ask me anything; resolve questions inside the band and report at the end.

PATHS (absolute; give these to every seat in every packet)
- Result repository: /Users/sebastienhenry/dark-factory/band-work/result
- Stage folder to create: /Users/sebastienhenry/dark-factory/band-work/result/stage-1
- Specification: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-1.md
- Event checker working directory: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs
- Python with pytest, httpx and playwright already installed: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

TASK
Build the service the specification describes, in stage-1/, with a Dockerfile and a RUN.md whose single command builds and starts it. Read the whole specification yourself, then paste it in full (numbered parts) into every packet that needs it, including the verifier's stage gate packet: seats cannot read this message.

ENGINEERING CONSTRAINTS
- The specification is the source of truth. Every sentence of it can be judged, including what no shipped check asks about. Do not open or read the event's test directory (pocketful/test); use the event checker only as a black-box signal, and when it fails, fix the behaviour the specification describes, for all inputs.
- Preferred stack, for a build with no moving parts: Python 3.12 standard library only (http.server with a threaded server and a large listen backlog, sqlite3 or in-memory state guarded by one lock), on the python:3.12-alpine image. Any other choice must build and run with no network at run time.
- Money invariants hold under 50 concurrent requests and retries: make each write atomic in one critical section; never check-then-write across two.
- Stage 1 has no screens: give @designer core work items with their own paths, so the work is shared.

GATES (the verifier runs these on one revision before the stage is accepted)
- Analyst acceptance suite green against the running container.
- Event checker, isolated mode, must print "claimed stage: 1":
  cd /Users/sebastienhenry/dark-factory/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo /Users/sebastienhenry/dark-factory/band-work/result --stage 1 --mode isolated --out /Users/sebastienhenry/dark-factory/band-work/checks/s1-<unique suffix>
  (The stage 2 line it prints afterwards is expected to fail. Each run needs a new --out directory.)
- Concurrency and retry stress against the stated invariants.
- Two-axis review.

DONE
Commit everything in the result repository, record the run log in runlog/stage1.md, and post your final report in this room with the accepted revision.
