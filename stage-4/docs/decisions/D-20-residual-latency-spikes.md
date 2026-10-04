# D-20 residual multi-second spikes in soak.py are measurement and host effects

**Question.** After D-19 a 60 s soak once showed `GET /me` 5.3 s and `POST /payments` 5.5 s with `nr_throttled` 0. Is there a remaining service-side cause?

**Evidence** (container `--cpus 2 --memory 2g`, shared host with load average 8 to 18 on 10 CPUs):
- Eight 60 s soaks on commit 9146189 (5 clean image, 3 with lock/handler timing). Throughput of the same load varied three-fold with host load (3469 to 10811 ops in 60 s); runs started at load 14-18 produced client maxima of 5-12 s and up to 20 client timeouts, runs at load 9 produced maxima of 2-3 s. `nr_throttled` was 0 in all eight.
- Lock (hypothesis d): in the instrumented image the global lock's maximum wait was 0.4 ms and maximum hold 4.2 ms over 60 s runs that reached about 2000 payments and 1300 requests; no hold over 100 ms. Not a sort-under-lock problem at soak sizes.
- Server-side time (handler entry to response written): non-auth endpoints at most 59 ms on a quiet run and 735 ms on the busiest run, while the client saw 2-10 s maxima on the same endpoints. Login/signup server time at most 3.6 s (queued behind the hash slot).
- Independent probes during three soaks of the final-candidate image (n=2^13, one slot): `GET /health` every 20 ms from inside the container and from a second host process: p99 3-7 ms, max 15-29 ms, 0 calls over 500 ms, while the soak client in the same window reported maxima of 1.2-2.6 s and p99 about 1 s.
- Client artefact (hypothesis e): soak.py is one asyncio process holding 50 coroutines, JSON encoding and httpx; at about 250 ops/s it is itself saturated, so its latencies include its own queueing, and it is descheduled when the host is busy.

**Choice.** No service change. The multi-second maxima come from host CPU contention (a busy shared machine delays both the Docker VM and the load generator) and from the single-process client, not from the lock, the hash slot, the accept queue or throttling. Judge on server-side evidence: independent probe maxima and handler times. Run the soak on a quiet host (load below the core count) to compare builds.

**Effect on acceptance tests.** None.

**Constraining text.** §2 "Per-request timeout | 5 s", "Concurrent requests | up to 50 in flight".
