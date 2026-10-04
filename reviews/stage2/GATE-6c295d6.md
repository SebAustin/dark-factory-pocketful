# Stage 2 gate

```
VERDICT REJECT 6c295d6fb5f0d1b178b9c3597a3a9da97e59a9de
```

All gates were decided on this one revision (clean detached worktree `/tmp/verifier-scratch/gate2`). 9d7ab5e is an ancestor and
`stage-1/` is byte-identical to it. The main working tree's `stage-1/` and `stage-2/` equal 6c295d6 and `git status` is empty for both.
Image: `docker build --no-cache -t verifier-gate2 .` from the folder holding `stage-2/RUN.md`, then `docker run -e PORT=18440 -p 18440:18440 --cpus 2 --memory 2g`;
healthy 2.07 s after start. STAGE1_URL is my own frozen stage-1 container (`verifier-gate` image, port 18427).
Host: analyst-s2 and analyst-s1img were up during G1 to G4 and had stopped before G6; unrelated host containers were idle. Load average 23.5 (G3 start), then
4.4 to 12.3 during G6.

## Gates

| Gate | Result | Command / evidence |
|---|---|---|
| G1 Ledger | **green** | `stage-2/docs/ledger.md`: 182 R2 rows and 21 Part B stage-1 change rows, 0 blank cells; the coverage table totals 182 = 83 api + 92 ui + 7 review/untestable (reasons listed). Script cross-check: 177 ids appear in a committed `test_R2_*` name or test body. The remaining 5 have a stated indirect proof: SCR.1 (the whole suite), SCR.7 (every UI test locates by testid), AMT.5 (exact formatted texts imply no sign), HOLD.15 (carried split suite), EXP.4 (fixture convention). Changed stage-1 rows are listed in Part B with decision records |
| G2 Plan | **green** | `docs/plan.md` and `docs/ui-plan.md` present; lead decision L6 is recorded in `runlog/state.md` (findings F1 to F6 converted to S2.8 and S2.U10/U11, all ACCEPTed: `S2.8-bf2e57d.md`, `S2.U11-8fda234.md`) |
| G3 Acceptance (stage 2) | **green** | `TARGET_URL=http://127.0.0.1:18440 STAGE1_URL=http://127.0.0.1:18427 python -m pytest stage-2/acceptance/stage2 -q` → **272 passed** |
| G4 Chain (stage 1) | **green** | `pytest stage-2/acceptance/stage1 -q` → **422 passed, 3 skipped**; `ACCEPTANCE_DOCKER=1 … test_operational.py` → **4 passed** (files, healthy within 60 s on PORT, default 8080, no outbound network) |
| G5 Supplied checker | **green** | `.venv/bin/python -m harness run --track pocketful --repo …/result --stage 2 --mode isolated --out …/checks/s2-gate-verifier-194526`, final lines: `stage 1: pass` · `stage 2: pass` · `stage 3: fail` (expected) · `highest contiguous stage: 2` · `claimed stage: 2 on the shipped checks` |
| G6 Invariants | **green** | `stress.py` 60 s: 8/8, 27746 requests, 0 5xx, 0 timeouts. `holds_stress.py` HOLDS_SECONDS=60: 193592 ops, p99 0.047 s, max 0.125 s, held after expiry 0, PASS (totals constant, available ≥ 0 at every sampled read, captured ≤ amount, captures linked). `soak.py soak`: PASS, 18835 requests, 0 5xx, every endpoint max ≤ 1.93 s, nr_throttled 0 of 1931. `soak.py big`: PASS (reset 1000/2000 users 0.80/1.51 s; export/import of 5000 payments 0.10/0.14 s). `burst_auth` ×3: max 1.06 s, 0 over 5 s. Memory 72 MiB; the container never exited |
| G7 Review | **red** | F6 below; everything else green |
| G8 User facing | **green** | below |

## G7 — review of 9d7ab5e..6c295d6 -- stage-2

Every app and web change in this range was item-reviewed and ACCEPTed (S2.1 to S2.8, S2.U1 to S2.U11; verdicts in this folder).
**Standards.** app: 2077 lines; largest module `store.py` at 499. One lock entry point (`STORE.hold()`, which also sweeps expiry); money and holds change only in
`store`; one view per resource. web: 1578 lines of small ES modules; one write controller (`writeForm` + `Attempt`), one refresh guard,
all text through `textContent`. No secrets, no `console.log`/`debugger`, no unused top-level functions (AST scan), one startup print.
**Spec.** No runtime network or CDN: the image holds `app/` and `web/` only; no `http(s)` URL other than the SVG namespace; system font stacks; no
`@import`/`url()`. CSP `default-src 'self'`, no inline scripts. Accept negotiation on `/requests` and `/authorizations` with `Vary: Accept`.
Upgrade path: stage-1 export → stage-2 import keeps tokens, receipts and retries (L5 sessions), verified behaviourally in S2.5, S2.8 and G8.

**F6 — Stage 1 §2 "a `RUN.md` with a command that builds and starts the service without manual setup" (owner: builder, `stage-2/RUN.md`).**
`stage-2/RUN.md` is the unchanged stage-1 copy. Its title is "Pocketful — stage 1"; it describes only the stage-1 API (no screens, no
authorizations); and its **repo-root command `docker build -t pocketful-s1 stage-1 && docker run …` builds and starts the stage-1 service, not
stage 2**. The load-check section points at `stage-1/tests/soak.py`, which does not exist in stage-2 (it moved to `tools/soak.py`). The
from-its-folder command is correct (G3 used it), but anyone following the repo-root command runs the wrong stage.
Repro: `sed -n 1,20p stage-2/RUN.md`; `grep -n "stage-1" stage-2/RUN.md`.
Expected: a stage-2 RUN.md whose commands build `stage-2` (both variants), describing the screens and the authorizations API, with current tool paths.

## G8 — screens (real Chromium)

- Walker `reviews/stage2/tools/plan.gate2.json`, **46 states × 5 widths (375, 390, 768, 1024, 1280) = 230 walks, 0 findings**: no horizontal scroll, every
  input labelled, focus visible on every tab stop, WCAG contrast, expected testids visible, clean console (only the refusal 4xx and aborted-request
  lines allowed). States: login (idle, wrong password, unreachable, submitting, signed-in), signup (idle, duplicate, short, signed-in), signed-in shell
  on 4 routes, wallet (available headline, held present, held absent JPY, 2^53 balance), pay success/already/invalid/refused/submitting/uncertain,
  request success/error, authorize success/error, activity list and empty, requests incoming/outgoing/paid/declined/cancelled/refused/uncertain/empty,
  split hint/preview/success/error, authorizations open/captured/voided/expired/capture refused/captured/keep-open/capture uncertain/authorise refused/empty.
  Screenshots: `reviews/stage2/shots/GATE-6c295d6/<width>/`.
- Behavioural scenarios at **all five widths**: wallet 12, requests+split 17, holds+upgrade 17, u10 7 → **265/265 ok**. They cover the latest refresh winning with
  out-of-order responses; a payment lost after commit retried with the same key (money once); a competing-client refusal keeping inputs; a stale
  request's pay button disappearing; a lost request-pay and capture retried with the same key; the upgrade (lost payment → export → import → retry in the
  same page, no reload, still signed in, pending request payable); the split preview equal to the server shares; edit then revert giving a new key.
- Feedback visibility (`feedback_cover_all.py`): 90/90 notices fully between the header and the tab bar (10 notice types × 9 viewports).
- Judgement against "Product and visual direction": calm, consistent system (serif display, one teal primary, a warm paper ground).
  Available is the headline (64 px) with total and held secondary. Refused (red, cross), uncertain (violet, dashed, question mark), success
  (green, check), held (amber, lock), pending, expired and voided are each distinct. People show by handle, amounts as "12.00 EUR", times as "Today 07:51 PM";
  raw ids are not shown except the RFC 3339 expiry the spec requires. Navigation is consistent (top nav ≥ 1000 px, tab bar below). No visible
  defect found. Note: full-page screenshots draw the fixed header and tab bar at the capture's scroll offset; that is a capture artifact.

## Findings
F6 (G7) only. All behavioural and visual gates are green.

## Next
@builder fixes F6 (`stage-2/RUN.md`), then the lead re-sends the gate on the new revision. A docs-only change means I re-run G4 (RUN.md
checks), G5 and a G7 diff check; the remaining gates carry if the diff touches only RUN.md.
