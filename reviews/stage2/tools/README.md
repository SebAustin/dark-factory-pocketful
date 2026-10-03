# Verifier stage 2 screen tools

- `walker.py`: Playwright (Chromium) walk of every planned screen state at 375, 390 and 1280 CSS px. For each state it saves a
  full-page screenshot and checks horizontal overflow, console errors, page errors and 5xx responses, unlabelled
  inputs, focus visibility (by tabbing), WCAG text contrast, and the expected `data-testid`s. It writes `report.json` and `report.md`
  and exits 1 on any finding.
- `plan.stage2.json`: the states from `runlog/stage2-spec.md`, with extreme data: long name and note, a 12-digit
  balance, JPY with no decimals, empty lists, an invalid amount, refused, uncertain (aborted `/payments`) and preview.
  Extend it per item packet.
- `selftest/`: a fake UI with one clean page and one page with planted defects. Confirm the walker still catches every defect:

```sh
PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
python3 reviews/stage2/tools/selftest/server.py 18431 &
$PY reviews/stage2/tools/walker.py --base http://127.0.0.1:18431 \
    --plan reviews/stage2/tools/selftest/plan.json --out /tmp/walker-selftest
# expect: good-* ok at every width; bad-planted FAIL with overflow, unlabelled, low_contrast,
#         focus_not_visible, console error and a missing testid
```

Screenshots for verdicts go under `reviews/stage2/shots/<item>-<rev>/<width>/`. Each one is looked at and judged,
not just captured.
