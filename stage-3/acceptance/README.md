# Stage 3 acceptance suites

Three black-box suites, one command each (from the repository root). Test names carry ledger ids:
`test_R3_KN_2_...` → R3-KN.2 (`stage-3/docs/ledger.md`), `test_R2_...` → stage 2, `test_R8_5_...` → stage 1.

```sh
PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
T=http://127.0.0.1:18100                     # the stage-3 service under test (your own port)
S1=http://127.0.0.1:18101                    # frozen stage-1 image (your own port)
S2=http://127.0.0.1:18102                    # frozen stage-2 image (your own port)

# 1. carried stage-1 suite (unchanged)
TARGET_URL=$T $PY -m pytest stage-3/acceptance/stage1 -q

# 2. carried stage-2 suite (API + screens); changed only by D-61 (authorization closed_at)
TARGET_URL=$T STAGE1_URL=$S1 $PY -m pytest stage-3/acceptance/stage2 -q

# 3. stage 3 suite: example/edge tests + property tests against the analyst's reference model
TARGET_URL=$T STAGE1_URL=$S1 STAGE2_URL=$S2 $PY -m pytest stage-3/acceptance/stage3 -q
```

Start the sources on your OWN ports (never another seat's containers; shared sources corrupt runs):

```sh
docker build -t <you>-s1img stage-1 && docker run -d --rm --name <you>-s1img -e PORT=<p1> -p <p1>:<p1> <you>-s1img
docker build -t <you>-s2img stage-2 && docker run -d --rm --name <you>-s2img -e PORT=<p2> -p <p2>:<p2> <you>-s2img
```

`stage3/s3lib.py` holds the reference model (decisions D-48 two-time selection, D-51 historical
holds, D-53 overdraft verdicts). `test_prop.py` builds a rich history (seeded dated payments,
payments, request pay, settlement, captures, void, open hold, backdated / zero / same-amount /
random corrections), predicts every correction verdict, then compares GET /me over the D-55 grid
(every boundary ±1 µs × known_at at every recorded instant ±1 µs) and statements over random windows
with the model, and checks Σ totals = seeded total and non-negativity in every view.
The designer's independent oracle (`stage-3/tools/oracle/`) is a second check run separately.
