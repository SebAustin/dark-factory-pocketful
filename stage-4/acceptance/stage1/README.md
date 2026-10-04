# Stage 1 acceptance suite

Black-box tests written from `stage-1/docs/ledger.md`. Every test name begins with the ledger id(s) it
proves (`test_R7_13_...` → R-7.13). Each test resets the service with its own fixture.

```sh
# from the repository root, against a running service
TARGET_URL=http://127.0.0.1:18100 \
  /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python -m pytest stage-1/acceptance -q

# also build and start the image for the §2 container checks (ports 18190-18199)
ACCEPTANCE_DOCKER=1 TARGET_URL=... python -m pytest stage-1/acceptance -q
```

`test_zz_crash_probes.py` runs last on purpose: its probes (deep nesting, huge exponents) may
crash or wedge a fragile service, and every earlier file should still report first.

Where the specification is open, tests accept each defensible answer and cite the decision
record (`docs/decisions/D-nn`); everywhere else the expected values are the specification's.
