# Stage 1 gate

```
VERDICT ACCEPT 9d7ab5e76ada506165f010ef4e751b746ffef108
```

Every gate was decided on this one revision, in a clean detached worktree (`/tmp/verifier-scratch/gate-9d7ab5e`).
Main HEAD 4e7d80d has stage-1 byte-identical to 9d7ab5e, and `git status --short -- stage-1` was empty before the checker ran.
25fc824 (the last stage-1 code change) is an ancestor. Image: `docker build --no-cache -t verifier-gate .`, run from the folder
holding RUN.md, then `docker run -e PORT=18420 -p 18420:18420 --cpus 2 --memory 2g verifier-gate`; healthy 0.68 s after start.

Host at gate time: no seat containers were running during the timing gates (analyst-s1 was up during G1/G3 and had stopped
before G6). Unrelated host containers were present: paypalaihackathon-postgres-1, quant-postgres, quant-redis, pe_platform_db and five idle
unnamed ones. Load average 6.4 at G3; 17.9 → 10.0 during the G6 stress (the checker had just finished building); 10.3 → 6.4 during the soak and big runs; 5.8 at the burst.

## Gates

| Gate | Result | Command / evidence |
|---|---|---|
| G1 Ledger | **green** | `stage-1/docs/ledger.md`: 228 rows, 0 blank cells; the coverage table totals 228 = 210 tested + 12 ops + 6 untestable with reasons (R-1.4, R-1.11, R-2.11, R-4.30, R-8.63, R-10.18). Script cross-check: 198 ids have a named `test_R…` in `acceptance/`, 28 are explained in the proof-naming notes, and R-X.1/R-X.2 have `test_RX_1_precedence_matrix` and `test_RX_2_validation_before_not_found`. 0 ids unaccounted. Spot check of 10 constraining phrases from §3.4, §4, §8, §10 and §11 (e.g. "at most 64", "need not survive", "nonmembers", "fifth idempotent"): all present |
| G2 Plan | **green** | `stage-1/docs/plan.md` present. No analyst PASS; lead decision L2 is recorded in `runlog/state.md` (plan gate closed after round 1, with findings P1 to P6 converted to S1.11 and verified ACCEPTs: `reviews/stage1/S1.11-S1.14-2e25cdb.md`, `S1.7-af5270c.md`, `S1.6-0b87d7f.md`) |
| G3 Acceptance | **green** | `TARGET_URL=http://127.0.0.1:18420 python -m pytest stage-1/acceptance -q` → **422 passed, 3 skipped**, 0 failed (the 3 skips are the container checks). `ACCEPTANCE_DOCKER=1 … pytest stage-1/acceptance/test_operational.py -v` → **4 passed** (files exist, healthy within 60 s on PORT, default 8080, health served on an `--internal` network with no outbound access) |
| G4 Chain | n/a | first stage |
| G5 Supplied checker | **green** | `cd …/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo …/result --stage 1 --mode isolated --out …/checks/s1-gate-verifier-174743`, final lines: `stage 1: pass` · `stage 2: fail` (expected) · `highest contiguous stage: 1` · `claimed stage: 1 on the shipped checks` |
| G6 Invariants | **green** | `STRESS_SECONDS=60 stress.py`: 8/8 PASS (drain, same-key ×50, 50 pays on one request, pay/decline/cancel races, settlement semantics, 50 concurrent settlements, same-key settlement, 60 s mixed at 50 in flight), 19615 requests, 0 5xx, 0 bad bodies, 0 timeouts. `soak.py soak`: PASS, 15591 requests, 0 5xx, 0 timeouts, every endpoint max ≤ 2.07 s; cpu.stat nr_throttled **0 of 1240**. `soak.py big`: PASS, reset 1000 users 0.74 s, 2000 users 1.56 s, export/import of 5000 payments 0.09 / 0.14 s. `burst_auth.py` ×3: signup max 1.06 to 1.10 s, login max 1.07 to 1.08 s, 0 over 5 s. Memory 31.7 MiB / 2 GiB afterwards; container never exited. The §1 invariants (sum equals seeded total, no negative balance at any sample, a request pays at most once) are checked by each tool |
| G7 Review | **green** | below |
| G8 User facing | n/a | stage 1 is HTTP only |

## G7 — review of a01ead4..9d7ab5e -- stage-1

Every app change in this range was item-reviewed and accepted (S1.1 to S1.8, S1.11 to S1.15; verdicts in this folder),
except the two named in the packet, which were reviewed here:
- **7a9d1cf (S1.17, builder)**: `RFC3339_RE` accepts `[Tt]` and `[Zz]`; `parse_rfc3339` upper-cases before
  `fromisoformat`; `\A…\Z` anchors were added in 2e25cdb. It matches RFC 3339 §5.6 and has a unit test. Accept.
- **6a73e1f (acceptance, analyst)**: implements lead decision L3. A 5000-digit `offset` gives 200 with `{…: [], has_more: false}`;
  a 5000-digit `limit` stays 422. It matches §5 ("`offset` | integer 0 or more", 422 only for "values exceeding a stated maximum"). Accept.

**Standards.** 1526 lines across 13 modules, largest `store.py` at 302. One lock and one money-moving module (`store.apply_transfer` and
`apply_batch`). The error envelope is produced in one place (`errors.ApiError` plus the `send_error` override), and every list uses one ordering
rule (`store.newest_first`). Numeric bounds sit in `validation.integral` and the canonical form in `validation.canonical`. No secrets,
no debug output (one startup line), no unused top-level functions (AST scan).

**Spec.**
- §6 "Plaintext password storage is not permitted": I exported after a reset and a signup. Neither password string appears, and the
  stored values are `scrypt$512$8$1$…` (seeded) and `scrypt$8192$8$1$…` (signup).
- §2 RUN.md: the single command `docker build -t pocketful-s1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1` works from its
  folder (G3 used it); the repo-root variant is kept. The Dockerfile is `python:3.12-alpine` with stdlib only and copies `app/`; no runtime network is needed (G3 R2.4).
- No code was found that special-cases test inputs.

Notes (non-blocking, carried from item reviews): the scrypt cost is N=2^13 for signup and 2^9 for seeded users (no spec floor); a
body nested deeper than 512 is 400 (judgement "does not parse"); users with equal seeded passwords share one salt (D7).

## Findings
None.

## Next
@lead records stage 1 as accepted at 9d7ab5e and proceeds to stage 2.
