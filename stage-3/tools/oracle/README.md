# stage-3/tools/oracle — independent reference model and differential tool

Written from the stage 3 specification and the analyst's decisions D-41..D-60, **not** from the builder's code.

| File | Purpose |
|---|---|
| `model.py` | Pure reference model of money history: balances at `(as_of, known_at)`, statements, hold intervals, correction outcomes. No I/O. |
| `selftest_model.py` | 12 hand-computed cases (numbers worked out on paper from the spec). `python3 selftest_model.py` |
| `diff_run.py` | Drives random operations against a real service and the model in lockstep; diffs every historical read; stress phase. |
| `fake_service.py` + `selftest_diff.py` | A stand-in service that can plant 14 divergences; the self-test proves the tool catches each one and passes a clean stand-in. |

```sh
PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
$PY stage-3/tools/oracle/selftest_model.py
$PY stage-3/tools/oracle/selftest_diff.py                 # clean stand-in passes, every planted bug is caught
TARGET_URL=http://127.0.0.1:18300 $PY stage-3/tools/oracle/diff_run.py --ops 150 --seed 1 --concurrent 10
# options: --keep-going (collect every divergence), --skip settlement,request,..., --no-protocol (stand-ins)
```
Exit 0 only when nothing diverged. The first divergence prints the model's answer, the service's answer, a `curl` repro and the
last 25 operations.

## What the model encodes (spec quote -> rule)
- **Payment timestamps / revision 1** — `created_at` is revision 1's amount time: `effective_at = recorded_at = created_at` (S3 "Effective time"; D-47).
- **Opening balances** — `opening = seeded ending balance − net effect of the ORIGINAL seeded payments`; corrections never change it; new accounts 0 (D-45).
- **`known_at` selection** — per payment the latest revision with `recorded_at <= known_at`; none yet -> contributes nothing; omitted -> everything known when the read begins (D-43/D-48).
- **Effective-time replacement** — a selected revision replaces the earlier amount and moves money at **its own** `effective_at` (D-48); one entry per payment, "no correction is counted alongside the revision it replaces".
- **`as_of` inclusive**, before everything -> opening, future -> current, echoed exactly; **`known_at`** echoed exactly (D-43).
- **Statement** — half-open `[from, to)`, oldest first by `(selected effective_at, payment id by code point)`, `opening` = balance just before `from`, `closing` = just before `to`, `opening + Σ delta = closing`, `balance_after` cumulative from the full-window opening and **independent of limit/offset**, zero-amount revisions are entries with delta 0, only the caller's own payments (D-48/D-49/D-44).
- **`from > to` is 422, `from = to` is empty** (D-54). Default `to` is the read instant.
- **Snapshots** — frozen result, same pages later whatever writes/corrections/lifecycle events happen; other user's / unknown / pre-reset token 404; `from`/`to`/`known_at` (even empty) with a snapshot 422 (D-50).
- **Corrections** — error order 422 fields -> 404 -> 403 (receiver too) -> `linked_payment_immutable` (settlement members, captures) -> `stale_revision` -> `insufficient_funds` (current available of the debited party) -> `historical_overdraft` -> 201 (D-46/D-53/D-59); `effective_at` echoed exactly as supplied; replay returns the **original** revision with 200 even after newer revisions; refused corrections claim no key (D-57); `/revisions` readable by the two parties only (D-47).
- **`historical_overdraft`** — corrected history of the two parties, every distinct boundary <= now (selected effective times and hold event times) plus the opening, all movements at one instant applied together, `total >= 0` and `available = total − held >= 0` (D-53).
- **Historical holds** — start at creation; a nonfinal capture reduces at capture time; a final capture, void or expiry releases the remainder at that event's time; expiry at `expires_at` is known once creation is known (also for future `as_of`); other events are known only at their own time (`<= known_at`); `balance = total`, `available = total − held` in the **same** view (D-51). `closed_at`: null while open, closing capture's instant / void instant / `expires_at` (D-51).
- **Conservation** — the sum of all wallets' `total` equals the seeded total in **every** `(as_of, known_at)` view (D-55); no total or available negative at any past boundary of the final history.
- **Clock** (D-41) — every server-assigned instant is unique and strictly increases in commit order; recorded times of one payment strictly increase; `expires_at = created_at + ttl` with microseconds kept.
- **Concurrency** (D-60) — 20 simultaneous corrections with the same `expected_revision`: at most one succeeds (exactly one when the model accepts any); views frozen in the past (`known_at` behind every write) never move while 20 writers and 30 readers run 50 in flight.

## Protocol checks (default on)
Instant grammar (naive, bare date, empty, `T`-less, `:60`, `+24:00`, 10 fraction digits all 422; `Z/z/T/t`, 1-9 digits and any offset accepted),
decoded `+` repaired in queries only, last repeated parameter wins, unknown parameters ignored, `/me` without temporal parameters keeps the stage 2
key set, statement and entry key sets, the stage 2 payment object (13 keys) inside entries, correction body defects (19 cases, 422 before 404/403),
missing key / no token / no JSON object, feed unchanged by corrections (D-56), reset with a future `created_at` or a negative opening is 422 and changes nothing,
seeded `created_at` kept exactly as supplied and omitted = reset time (<= now, before API payments), snapshot token 404 after a reset.

## Tolerances and limits (be aware)
- The model cannot see the service's read instant N. Queries whose answer depends on "now" (default `to`, `/me` holds without `as_of`) are accepted if
  they match the model at any whole second from -1 to +2 around the request start; an off-by-one-second *service* bug there is therefore not reported.
  Explicit instants (the bulk of the grid, including +-1 microsecond around every recorded instant) are exact.
- Instants finer than a microsecond are not generated (the service clock is microseconds, D-41); `.123456789` parsing is covered by `selftest_model.py` only.
- Seeded **closed** holds and the **import/upgrade** of populated stage-1/stage-2 exports (D-52) are not driven here; the seeded **open** hold is.
- The self-test stand-in answers from the same model, so it proves the tool catches divergences and that the tool and model agree with themselves; the model's
  own correctness rests on `selftest_model.py` (hand-computed) and on review against the spec.
