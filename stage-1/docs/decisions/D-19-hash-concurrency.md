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
