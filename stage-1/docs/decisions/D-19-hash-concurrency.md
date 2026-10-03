# D-19 limit concurrent password hashing

**Question.** Why do requests exceed 5 s under 50 in flight when signups and logins are in the mix, and what is the smallest fix?

**Evidence** (container `--cpus 2 --memory 2g`, noisy shared host; `soak.py`, `hash_load_probe.py`):
- One scrypt n=2^14 costs 44 ms of CPU; 16 in parallel threads take 0.5 s wall, 50 take 1.6 s (it scales to the host cores).
- `/sys/fs/cgroup/cpu.stat` after the soak: `nr_throttled 452` of 974 periods, 260 s throttled. With 50 concurrent signup/login callers the container is throttled in 87 of 90 periods. `cpu.max` is `200000 100000`: 200 ms of CPU per 100 ms; parallel scrypt threads spend it in a few ms and every thread of the process, including a plain `GET /me`, then stalls until the next period.
- Not the global lock (hash runs outside it; 50 payments alone: p50 ~120 ms, 0 throttled) and not the accept backlog.
- Mixed load, 10 signup + 10 login + 30 payment workers, 8 s: payments p50 388-496 ms, p99 2.6-3.8 s, max 4.2 s, 317-442 completed, throttled 21-32 of ~90 periods; one run had a request over 5 s (transport timeout). Soak 60 s: `POST /payments` max 8.2 s on a busy host, 2.5 s on a quiet one.

**Choice.** Allow one hash at a time in the process: a `threading.BoundedSemaphore(1)` around `_derive` in `hash_password` and `verify_password`; `hash_many` (reset) bypasses it. Keep scrypt n=2^14, r=8, p=1.

**Measured effect of the candidates** (same mix, medians of 2 runs; payments in the mix):

| variant | payment p50 / p99 / max (ms) | payments done | throttled periods |
|---|---|---|---|
| unchanged | 442 / 2650 / 3470-4200 | 317-442 | 21-32 of ~90 |
| 1 hash at a time | 85-96 / 850-960 / 1260-1660 | 1357-1695 | 0 |
| 2 hashes at a time | 114-139 / 1600-1930 / 2100-3700 | 864-1093 | 41-75 of ~85 |
| n=2^13, no limit | 315-347 / 1800-2460 / 2100-2800 | 450-572 | 5-6 |
| 1 at a time and n=2^13 | 79-82 / 1900-2100 / 3000-3350 | 1132-1262 | 0 |

Soak 60 s with 1 at a time: PASS, 28405 requests, 0 5xx, 0 over 5 s, non-auth p50 4-9 ms, p99 under 1.1 s, signup/login p50 1.9 s, max 2.45 s (50 simultaneous hashes queue 50 x 44 ms). Two at a time still throttles because two hashing threads plus the interpreter thread exceed 2 CPUs; n=2^13 alone does not stop the throttling.

**Effect on acceptance tests.** None: the stored hash format and parameters are unchanged; seeded users keep verifying with their stored n.

**Constraining text.** §2 "Per-request timeout | 5 s", "CPU | 2 vCPU"; §6 password hashing function.

## Revision S1.13-R1: cost and slot count (verifier F7, lead guidance)

The one-slot, n=2^14 build bursts 50 signups + 50 logins in 2.2 s on a quiet host but 5.1-5.9 s on the verifier's busy one (a single n=2^14 hash took 104 ms there). Candidates, measured in the container (`--cpus 2 --memory 2g`) with `reviews/stage1/tools/burst_auth.py` (50 signups, then 50 logins, 3 runs per round, 2 rounds, host load about 8):

| candidate | burst max signup / login | throttled periods (burst runs) |
|---|---|---|
| slots=1, n=2^14 (5ff293a) | 2.16-2.22 s / 2.12-2.41 s | 0 |
| (a) slots=2, n=2^14 | 1.05-1.24 s / 1.06-1.14 s | 42 of 75, 83 of 154 |
| (b) slots=1, n=2^13 | 1.06-1.20 s / 1.07-1.22 s | 0 |
| (c) slots=2, n=2^13 | 0.54-0.56 s / 0.53-0.56 s | 25 of 48, 45 of 92 |
| (d) slots=1, n=2^12 | 0.51-0.56 s / 0.52-0.55 s | 0 |

Soak 60 s (2 rounds each): (a) PASS, 0 calls over 5 s, throttled 101 and 133 of about 610 periods; (b) PASS, 0 over 5 s, throttled 0 and 0. Two slots plus the interpreter thread exceed the 2 CPU quota during a burst, so (a) and (c) still throttle.

**Choice: (b) one slot, n=2^13, r=8, p=1.** It meets burst <= 2.5 s with margin on this host and still under 2.5 s if the host is 2x slower, and never throttles. n=2^14 with two slots meets the burst limit but throttles in about a fifth of the soak's periods, which the guidance rules out.

Seeded fixture users: `SEED_N` goes from 2^11 to 2^9 so a 2000-distinct-password reset stays well under its limit (reset timings, 5 runs each, quiet host): n=2^11 3.0 s (1000) / 6.0-6.2 s (2000); n=2^10 1.5 s / 3.1 s; n=2^9 0.8 s / 1.5-1.6 s. Stored hashes carry their parameters, so seeded and older users still verify. Final build: reset 1000 users 0.9 s, 2000 users 1.6-1.7 s; burst_auth max 1.10 s signup, 1.08-1.24 s login, 0 calls over 5 s.
