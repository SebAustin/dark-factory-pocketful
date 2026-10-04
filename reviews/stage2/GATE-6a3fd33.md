# Stage 2 re-gate

```
VERDICT ACCEPT 6a3fd334b9a64588b9d821ba654ae47538cba7bc
```

Previous gate: `reviews/stage2/GATE-6c295d6.md` (REJECT on F6 only). Confirmed for this revision:
- `git diff --stat 6c295d6 6a3fd33 -- stage-1 stage-2` → **only `stage-2/RUN.md`** (46+, 13−); 6c295d6 is an ancestor.
- 9d7ab5e is an ancestor and `stage-1/` is byte-identical to it.
- The main working tree's `stage-1/` and `stage-2/` equal 6a3fd33; `git status` is empty for both before the checker.
Clean detached worktree of 6a3fd33; gate image `docker build --no-cache` from stage-2, run `--cpus 2 --memory 2g -e PORT=18441`; my own frozen stage-1
container (port 18427) as STAGE1_URL. Host: only verifier containers and unrelated idle host containers; load average 4.6 to 8.1.

## Gates

| Gate | Result | How decided |
|---|---|---|
| G1 Ledger | **green (carried)** | The diff does not touch `stage-2/docs/`; see GATE-6c295d6 (182 R2 rows + 21 Part B, 0 blank cells, all ids accounted for) |
| G2 Plan | **green (carried)** | Unchanged; L6 in `runlog/state.md` |
| G3 Acceptance (stage 2) | **green (re-run)** | `TARGET_URL=http://127.0.0.1:18441 STAGE1_URL=http://127.0.0.1:18427 python -m pytest stage-2/acceptance/stage2 -q` → **272 passed** |
| G4 Chain (stage 1) | **green (re-run)** | `pytest stage-2/acceptance/stage1 -q` → **422 passed, 3 skipped**; `ACCEPTANCE_DOCKER=1 … test_operational.py` → **4 passed** |
| G5 Supplied checker | **green (re-run)** | `.venv/bin/python -m harness run --track pocketful --repo …/result --stage 2 --mode isolated --out …/checks/s2-gate2-verifier-200816` → `stage 1: pass` · `stage 2: pass` · `stage 3: fail` (expected) · `highest contiguous stage: 2` · `claimed stage: 2 on the shipped checks` |
| G6 Invariants | **green (carried)** | No code changed; see GATE-6c295d6 (stress 8/8 at 60 s, holds_stress 60 s PASS, soak max 1.93 s and 0 throttled, big PASS, burst max 1.06 s, 0 5xx) |
| G7 Review | **green (re-run on the diff)** | F6 closed, see below |
| G8 User facing | **green (carried)** | No `web/` or `app/` change; see GATE-6c295d6 (230/230 walks at 375/390/768/1024/1280; 265/265 scenarios; 90/90 feedback visible; screenshots judged) |

## G7 — RUN.md diff (closes F6)
- Title "Pocketful — stage 2"; it describes the screens, the authorizations API, Accept negotiation and the stage-1 upgrade path.
- **Both commands were run exactly as written**. From `stage-2/`: `docker build -t pocketful-s2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2`.
  From the repo root: `docker build -t pocketful-s2 stage-2 && docker run …`. Each gave `/health` `{"status":"ok"}`, `/` 200 `text/html`, and
  `/authorizations` without an HTML Accept → 401 JSON. The repo-root image's `/me` returns `total/available/held`, so it is the stage-2 service.
- Paths: `stage-2/tools/{stress,soak,holds_stress}.py`, `stage-2/tests/upgrade_check.py` and `stage-2/acceptance/{stage1,stage2}` all exist; the only
  remaining "stage-1" text is the `STAGE1_URL` placeholder for the upgrade source.

## Findings
None. F6 is closed.

## Next
@lead records stage 2 as accepted at 6a3fd334b9a64588b9d821ba654ae47538cba7bc.
