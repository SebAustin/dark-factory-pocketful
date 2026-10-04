# Stage 3 gate

```
VERDICT REJECT aaf1ee2db56a74f01e6db9f96b51fe34536e4bf6
```

All gates were decided on this one revision (clean detached worktree). 6a3fd33 is an ancestor; `stage-1/` equals 9d7ab5e and `stage-2/` equals 6a3fd33 byte for byte;
the main working tree's stage folders equal the gate and `git status` is empty for them. Image: `docker build --no-cache` in `stage-3/`, run
`--cpus 2 --memory 2g -e PORT=18460`, healthy 0.76 s after start. STAGE1_URL/STAGE2_URL are my frozen images (tags `verifier-gate` 9d7ab5e and `verifier-gate3` 6a3fd33, ports
18427/18442). Host: no other seat containers; an unrelated `hashicorp/terraform-mcp-server` container was idle; load average 4.1 to 9.

## Gates

| Gate | Result | Command / evidence |
|---|---|---|
| G1 Ledger | **green** | `stage-3/docs/ledger.md`: 128 R3 rows plus the Part B changed rows (143 total), 0 blank cells; coverage 114 example + 14 property, 0 untestable. Decision records D-41 to D-61 present (21). Cross-check: 124 R3 ids appear in committed `test_R3_*` names or bodies; 4 rows cite stale test names but are proven by other committed tests (REV.3 → `test_R3_TS_4_TS_8_…` and the revision checks in test_corrections/test_upgrade3; SET.5 → `test_R3_ST_14_…`; HH.10/HH.12 → `test_R3_INV_1_INV_2_ME_4_ME_9_HH_model_every_view`). Note for the analyst: refresh those proof names |
| G2 Plan | **green** | `stage-3/docs/plan.md` present; L7, L8 (revised) and L9 recorded in `runlog/state.md`; the plan-gate finding (snapshots across import) was resolved by L8 and the accepted S3.3 resubmission |
| G3 Acceptance (stage 3) | **green** | `pytest stage-3/acceptance/stage3 -q` (TARGET + STAGE1/STAGE2 = mine) → **134 passed** |
| G4 Chain | **green** | `stage-3/acceptance/stage1` → **422 passed, 3 skipped**; `ACCEPTANCE_DOCKER=1 … test_operational.py` → **4 passed** (incl. no outbound network); `stage-3/acceptance/stage2` (API + UI) → **272 passed**. Walker `reviews/stage2/tools/plan.gate2.json` at 390/1280 → **92/92 clean** (screenshots `reviews/stage3/shots/GATE-aaf1ee2/`); my UI scenarios (wallet 12, requests/split 17, holds/upgrade 17, u10 7) → **106/106** at 390 and 1280 |
| G5 Supplied checker | **green** | `.venv/bin/python -m harness run --track pocketful --repo …/result --stage 3 --mode isolated --out …/checks/s3-gate-verifier-210806` → `stage 2: pass` · `stage 3: pass` · `stage 4: fail` (expected) · `highest contiguous stage: 3` · `claimed stage: 3 on the shipped checks` |
| G6 Invariants | **green** | My `hist_probe.py` 30 s: 12249 writes with 1087 interleaved historical reads, PASS (per-view Σ = seeded, the frozen past view unchanged, statements chained, snapshot pages identical, the 20-way same-revision race → exactly one 201), 0 slow, 0 5xx. `ledger_stress.py` 60 s: 51302 requests, 4134 correction races, 522 snapshots re-paged, 682 views, max 0.391 s, PASS; `big`: 20000 seeded payments, every read ≤ 0.03 s, PASS. Designer oracle `diff_run.py --seed 5`: normal, `--upgrade 1` and `--upgrade 2`, each 1059 historical reads, **PASS no divergence**. `holds_stress.py` 60 s: 175496 ops, max 0.142 s, PASS. `stress.py` 60 s: 8/8, 0 5xx. `soak.py soak`: PASS, 0 5xx. `snapshot_growth.py 5500`: memory 119.5 → 119.2 MiB (flat), export 0.4 MB, unchanged import 204. The container never exited |
| G7 Review | **red** | F7, F8 below |
| G8 User facing | **green** | Stage 3 adds no screen: `stage-3/web` is identical to `stage-2/web` (path and blob hashes); the G4 re-walk and scenarios are clean |

## G7 — review of 6a3fd33..aaf1ee2 -- stage-3
Every app change was item-reviewed and ACCEPTed (S3.1 aa3922c, S3.2 e02f93d, S3.3 c8943d4, S3.4 6757ba3, S3.5 41cf24c, S3.6 c03a99e). Upgrades over populated
stage-1/2 state, re-run here on **fresh** exports from my frozen images (`upgrade_driver.py populate` then `check`): **26 ok / 0 fail**. That covers imports,
tokens, 35 original-body replays, failed keys, statements reconciled per user, Σ in as_of views, settlement members and captures → `linked_payment_immutable`,
and a correction with an identical replay. No runtime network or CDN (no URL other than the SVG namespace; operational test with no outbound network
passes). Standards: one clock and instant key (`instants`), append-only revisions (`ledger`), one place for selection and hold history, one correction handler
with all checks before writes; the largest module is `store.py` at 554 lines.

**F7 — Stage 1 §2 "a `RUN.md` with a command that builds and starts the service without manual setup" (owner: builder, `stage-3/RUN.md`).**
`stage-3/RUN.md` is the unchanged stage-2 copy: the title is "Pocketful — stage 2", and the **repo-root command `docker build -t pocketful-s2 stage-2 && …` builds
and starts the stage-2 service**. It does not mention statements, corrections, `as_of`/`known_at` or the stage-1/2 upgrade into stage 3, and all
test and tool paths point at `stage-2/…` (e.g. `stage-2/acceptance/stage1`, `stage-2/tools/stress.py`). The from-its-folder command is correct; the gate
image was built with it. This is the same defect as stage 2's F6.
Repro: `sed -n 1,20p stage-3/RUN.md`; `grep -n "stage-2" stage-3/RUN.md`.

**F8 — standards: no dead code (owner: builder, `stage-3/app`).** `transfer_io.is_stage1_state` (superseded by `is_upgrade_state`) and
`instants.key_of_micros` are defined but never referenced.
Repro: `grep -rn "is_stage1_state\|key_of_micros" stage-3/app stage-3/tests` → definitions only.

## Findings
F7 (blocking, same class as stage-2 F6) and F8 (small). Everything behavioural is green.

## Next
@builder fixes F7 and F8 in one commit touching `stage-3/RUN.md` and the two dead definitions. Then the lead re-sends the gate. If the diff is only
those, I re-run G3 (cheap), G4 stage-1 plus the docker checks, G5 and G7 (RUN.md commands run as written), and carry G1, G2, G6 and G8.
