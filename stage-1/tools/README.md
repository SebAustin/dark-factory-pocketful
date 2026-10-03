# stage-1/tools

`stress.py` — concurrency and retry stress tool for any running stage 1 service.

    TARGET_URL=http://127.0.0.1:<port> /Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python stage-1/tools/stress.py

Optional: `STRESS_SECONDS` (mixed load length, default 20), `STRESS_SEED` (replay a run).
Scenarios a, b, c1, c2, d1, d2, d3, e each reset the service with their own fixture. Exit 0 only if every
scenario passes; any 5xx, 4xx without the JSON error envelope, or timeout (>5 s) fails the run.
Needs only stdlib and httpx.
