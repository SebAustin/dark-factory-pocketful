# Stage 4 acceptance suites

Four black-box suites, one command each (repository root). Test names carry ledger ids
(`test_R4_BERR_1_...` → R4-BERR.1 in `stage-4/docs/ledger.md`; R3/R2/R-ids for carried suites).

```sh
PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
T=http://127.0.0.1:<your port>      # stage-4 service under test
S1=…; S2=…; S3=…                     # frozen stage-1/2/3 images on YOUR ports only

TARGET_URL=$T $PY -m pytest stage-4/acceptance/stage1 -q
TARGET_URL=$T STAGE1_URL=$S1 $PY -m pytest stage-4/acceptance/stage2 -q
TARGET_URL=$T STAGE1_URL=$S1 STAGE2_URL=$S2 $PY -m pytest stage-4/acceptance/stage3 -q
TARGET_URL=$T STAGE1_URL=$S1 STAGE2_URL=$S2 STAGE3_URL=$S3 $PY -m pytest stage-4/acceptance/stage4 -q
```

Carried suites change only per D-75 (refund_of, correction_batch_id, L10/L12 snapshot restore).
`stage4/test_atomic.py` injects a failure on the LAST item of a batch for every rule (field, 404,
capture, refund, stale, refund floor, incomplete settlement, member instants, insufficient funds,
historical overdraft) and asserts that balances, revisions, statements, a snapshot and the
idempotency key are all unchanged; it also runs a 20-way single-vs-batch race and a 50-way load
with readers that must never see half a batch.
