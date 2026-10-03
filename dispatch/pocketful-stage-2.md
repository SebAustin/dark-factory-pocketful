@lead Run stage 2 of the pocketful track as a dark-factory run. This message is the only human input for this stage: do not ask me anything; resolve questions inside the band and report at the end.

PATHS (absolute; give these to every seat in every packet)
- Result repository: /Users/sebastienhenry/dark-factory/band-work/result
- Start from the accepted folder: /Users/sebastienhenry/dark-factory/band-work/result/stage-1 (frozen: do not change it)
- Stage folder to create: /Users/sebastienhenry/dark-factory/band-work/result/stage-2
- Specification: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-2.md (stage 1's specification still applies except where stage 2 changes it: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/pocketful/spec/stage-1.md)
- Event checker working directory: /Users/sebastienhenry/dark-factory/dark-factory-wearedevs
- Python with pytest, httpx and playwright (chromium installed): /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

TASK
Copy stage-1 to stage-2 (delete any nested .git in the copy), commit the unchanged copy, then extend it to the stage 2 specification: the browser product and the new API and model behaviour. Read the whole specification yourself, then paste it in full (numbered parts) into every packet that needs it, including the verifier's stage gate packet: seats cannot read this message.

ENGINEERING CONSTRAINTS
- The specification is the source of truth, including its product and visual direction and every element name and attribute it gives for the screens. Do not open or read the event's test directory (pocketful/test); use the event checker only as a black-box signal.
- Screens are served by the same container, with every asset (fonts, scripts, styles) inside the image. No CDN, no network at run time. Plain HTML, CSS and JavaScript with no build step is preferred.
- Every stage 1 behaviour keeps working unless stage 2 explicitly changes it.
- Run three lanes: @analyst on the ledger and acceptance tests, @builder on the API and model, @designer on the screens. The verifier checks screens in a real browser at 390 px and 1280 px wide.

GATES (the verifier runs these on one revision before the stage is accepted)
- Stage 1 and stage 2 acceptance suites green against the stage-2 container.
- Event checker, isolated mode, must print "claimed stage: 2":
  cd /Users/sebastienhenry/dark-factory/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo /Users/sebastienhenry/dark-factory/band-work/result --stage 2 --mode isolated --out /Users/sebastienhenry/dark-factory/band-work/checks/s2-<unique suffix>
- Concurrency and retry stress; every screen state walked with screenshots; two-axis review.

DONE
Commit everything, record runlog/stage2.md, and post your final report in this room with the accepted revision.
