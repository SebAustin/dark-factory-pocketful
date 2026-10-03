# Stage 2 acceptance suites

Two black-box suites, one command each (from the repository root). Test names carry the ledger
ids: `test_R2_CAP_12_...` → R2-CAP.12 (`stage-2/docs/ledger.md`), `test_R8_5_...` → stage-1 row
R-8.5 (`stage-1/docs/ledger.md`).

```sh
PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python

# 1. carried stage-1 suite (unchanged except rows stage 2 changes: D-39, D-40)
TARGET_URL=http://127.0.0.1:18100 $PY -m pytest stage-2/acceptance/stage1 -q

# 2. stage 2 suite: API (httpx, test_api_*) and screens (playwright chromium, test_ui_*,
#    each screen test at 390 px and 1280 px; quality checks also at 375 px)
TARGET_URL=http://127.0.0.1:18100 STAGE1_URL=http://127.0.0.1:18101 \
  $PY -m pytest stage-2/acceptance/stage2 -q
```

`STAGE1_URL` is the team's frozen stage-1 image, used as the source of a real stage-1 export
for the upgrade rows (R2-UPG.*):

```sh
docker build -t analyst-s1img stage-1 && docker run -d --rm --name analyst-s1img -e PORT=18101 -p 18101:18101 analyst-s1img
docker build -t analyst-s2 stage-2   && docker run -d --rm --name analyst-s2   -e PORT=18100 -p 18100:18100 analyst-s2
```

Run the two suites separately (each folder has its own `conftest.py`). API-only:
`-k test_api`; screens only: `-k test_ui`. Expiry tests wait a few seconds of real time
(`authorization_ttl_seconds` 2–3 s); that is the behaviour under test, not synchronisation.
Where the specification is open, tests accept each defensible answer and cite the decision
record (`stage-2/docs/decisions/D-21`…`D-40`).
