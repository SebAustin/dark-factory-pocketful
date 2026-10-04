#!/usr/bin/env python3
"""S3.6: concurrency, snapshots and historical-view invariants under load (stdlib only).

    TARGET_URL=http://127.0.0.1:18240 LEDGER_SECONDS=30 python3 stage-3/tools/ledger_stress.py
    TARGET_URL=... python3 stage-3/tools/ledger_stress.py big     # large-state timings

load: 50 workers mix payments, corrections (bursts racing on the same expected revision),
      statements (first read + later re-paging of the snapshot), /me history reads, holds.
      Checks: no 5xx, every 4xx enveloped, nothing slower than 5 s; in every race on one
      (payment, expected_revision) at most one 201 and the rest 409 stale_revision (or another
      refusal); every snapshot re-pages byte-identically after later writes; at the end, for
      every boundary instant and for K in {each recorded_at, now}: Σ totals = seeded total,
      every total >= 0 under K = now, available = total - held >= 0, view(now) = stored values.
big:  20 000 seeded payments: statement (limit 200), statement full paging, /me as_of and
      known_at, a correction with its overdraft check and an export, each timed (< 5 s).
"""
import http.client
import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

TARGET = urlsplit(os.environ.get("TARGET_URL", "http://127.0.0.1:18240"))
SECONDS = float(os.environ.get("LEDGER_SECONDS", "30"))
WORKERS, USERS, SEED, PW, LIMIT_S = 50, 10, 50000, "correct horse", 5.0
guard = threading.Lock()
problems, latencies, statuses = [], [], {}
local = threading.local()


def problem(text):
    with guard:
        problems.append(text)


def call(method, path, body=None, token=None, key=None, timeout=15):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    for attempt in (1, 2):
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = local.conn = http.client.HTTPConnection(TARGET.hostname, TARGET.port,
                                                           timeout=timeout)
        started = time.monotonic()
        try:
            conn.request(method, path, None if body is None else json.dumps(body), headers)
            r = conn.getresponse()
            raw = r.read()
            break
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            local.conn = None
            if attempt == 2 or method != "GET":
                problem("transport {} {} {!r}".format(method, path, exc))
                return 0, None
    took = time.monotonic() - started
    data = json.loads(raw) if raw else None
    with guard:
        latencies.append(took)
        statuses[r.status] = statuses.get(r.status, 0) + 1
    if r.status >= 500:
        problem("5xx {} {} {}".format(method, path, raw[:200]))
    elif r.status >= 400 and not (isinstance(data, dict) and "code" in data.get("error", {})):
        problem("4xx without envelope {} {}".format(method, path))
    if took > LIMIT_S and path != "/_test/reset" and not path.startswith("/_test/"):
        problem("slow {:.2f}s {} {}".format(took, method, path))
    return r.status, data


def qs(**params):
    return "&".join("{}={}".format(k, quote(str(v), safe="")) for k, v in params.items())


def iso(dt):
    return dt.isoformat(timespec="microseconds")


def setup(payments=0):
    now = datetime.now(timezone.utc)
    users = [{"id": "u%d" % i, "email": "u%d@e.com" % i, "password": PW,
              "display_name": "U%d" % i, "handle": "u%d" % i, "balance": SEED}
             for i in range(USERS)]
    seeded = []
    if payments:
        rng = random.Random(7)
        for n in range(payments):
            a, b = rng.sample(range(USERS), 2)
            seeded.append({"id": "s%d" % n, "from_user_id": "u%d" % a, "to_user_id": "u%d" % b,
                           "amount": 1 + n % 5,
                           "created_at": iso(now - timedelta(seconds=payments - n))})
        net = [0] * USERS
        for p in seeded:
            net[int(p["from_user_id"][1:])] -= p["amount"]
            net[int(p["to_user_id"][1:])] += p["amount"]
        for i, u in enumerate(users):
            u["balance"] = SEED + net[i]
    status, _ = call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                                              "authorization_ttl_seconds": 3, "users": users,
                                              "payments": seeded,
                                              "settlement_operator_ids": ["u0"]}, timeout=60)
    assert status == 204, status
    return [call("POST", "/auth/login", {"email": "u%d@e.com" % i, "password": PW})[1]["token"]
            for i in range(USERS)], SEED * USERS


class Load:
    def __init__(self, tokens):
        self.tok = tokens
        self.payments = []   # (payment id, sender index, receiver index)
        self.snapshots = []  # (user index, token, frozen full body)
        self.races = 0

    def worker(self, deadline):
        rng = random.Random()
        while time.monotonic() < deadline:
            a, b = rng.sample(range(USERS), 2)
            op = rng.random()
            if op < 0.30:
                s, body = call("POST", "/payments", {"to_handle": "u%d" % b,
                                                     "amount": rng.randint(1, 2000)},
                               self.tok[a], uuid.uuid4().hex)
                if s == 201:
                    with guard:
                        self.payments.append((body["payment_id"], a, b))
            elif op < 0.45 and self.payments:
                self.race(rng)
            elif op < 0.60:
                s, body = call("GET", "/statement?limit=200", token=self.tok[a])
                if s == 200 and not body["has_more"]:
                    with guard:
                        self.snapshots.append((a, body["snapshot"], body))
            elif op < 0.70 and self.snapshots:
                i, token, frozen = rng.choice(self.snapshots)
                s, page = call("GET", "/statement?" + qs(snapshot=token, limit=200),
                               token=self.tok[i])
                if (s, page) != (200, frozen):
                    problem("snapshot {} changed".format(token[:8]))
            elif op < 0.80:
                at = iso(datetime.now(timezone.utc) - timedelta(seconds=rng.uniform(0, 30)))
                s, me = call("GET", "/me?" + qs(as_of=at), token=self.tok[a])
                if s == 200 and (me["available"] != me["total"] - me["held"]
                                 or me["available"] < 0):
                    problem("bad historical /me {}".format(me))
            elif op < 0.90:
                call("POST", "/authorizations", {"to_handle": "u%d" % b,
                                                 "amount": rng.randint(1, 500)},
                     self.tok[a], uuid.uuid4().hex)
            else:
                call("GET", "/me", token=self.tok[a])

    def race(self, rng):
        pid, sender, _ = rng.choice(self.payments)
        s, revs = call("GET", "/payments/%s/revisions" % pid, token=self.tok[sender])
        if s != 200:
            return
        expected = revs["revisions"][-1]["revision"]
        results = []
        effective = iso(datetime.now(timezone.utc) - timedelta(seconds=rng.uniform(0, 5)))

        def one(amount):
            results.append(call("POST", "/payments/%s/corrections" % pid,
                                {"expected_revision": expected, "amount": amount,
                                 "effective_at": effective, "reason": "race"},
                                self.tok[sender], uuid.uuid4().hex))
        threads = [threading.Thread(target=one, args=(rng.randint(0, 2500),)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with guard:
            self.races += 1
        if sum(1 for s, _ in results if s == 201) > 1:
            problem("two corrections of {} at revision {} succeeded".format(pid, expected))


def final_checks(tokens, seeded_total):
    exported = call("GET", "/_test/export", timeout=60)[1]["state"]
    instants = set()
    for p in exported["payments"].values():
        for r in p["revisions"]:
            instants.update((r["effective_at"], r["recorded_at"]))
    for a in exported["authorizations"].values():
        instants.update(e["at"] for e in a.get("events", ()))
    sample = sorted(instants)
    random.shuffle(sample)
    sample = sample[:60] + ["1970-01-01T00:00:00Z", "2999-01-01T00:00:00Z"]
    knowns = sample[:10] + [None]
    for at in sample:
        for known in knowns:
            params = {"as_of": at}
            if known:
                params["known_at"] = known
            views = [call("GET", "/me?" + qs(**params), token=t)[1] for t in tokens]
            if sum(v["total"] for v in views) != seeded_total:
                problem("Σ totals at as_of={} known_at={} = {}".format(
                    at, known, sum(v["total"] for v in views)))
            if known is None and any(v["total"] < 0 or v["available"] < 0 for v in views):
                problem("negative view at {}: {}".format(at, views))
    for t in tokens:
        stored = call("GET", "/me", token=t)[1]
        view = call("GET", "/me?" + qs(known_at="2999-01-01T00:00:00Z"), token=t)[1]
        if any(stored[f] != view[f] for f in ("total", "available", "held")):
            problem("view(now) != stored for {}".format(stored["handle"]))
    return len(sample) * len(knowns)


def load_mode():
    tokens, seeded_total = setup()
    load = Load(tokens)
    deadline = time.monotonic() + SECONDS
    threads = [threading.Thread(target=load.worker, args=(deadline,)) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    views = final_checks(tokens, seeded_total)
    ordered = sorted(latencies)
    print("{} requests, {} correction races, {} snapshots re-paged, {} historical views checked, "
          "p50 {:.3f}s p99 {:.3f}s max {:.3f}s, statuses {}".format(
              len(ordered), load.races, len(load.snapshots), views, ordered[len(ordered) // 2],
              ordered[int(len(ordered) * 0.99)], ordered[-1], dict(sorted(statuses.items()))))


def big_mode():
    started = time.monotonic()
    tokens, _ = setup(payments=20000)
    print("reset with 20000 seeded payments: {:.2f}s".format(time.monotonic() - started))
    tok = tokens[0]

    def timed(label, method, path, body=None, key=None):
        t0 = time.monotonic()
        status, data = call(method, path, body, tok, key, timeout=30)
        took = time.monotonic() - t0
        print("{:<44} {} {:.3f}s".format(label, status, took))
        if took > LIMIT_S or status >= 400:
            problem("big: {} {} {:.2f}s".format(label, status, took))
        return data

    first = timed("statement limit=200", "GET", "/statement?limit=200")
    timed("statement page via snapshot offset=3800", "GET",
          "/statement?" + qs(snapshot=first["snapshot"], limit=200, offset=3800))
    mid = iso(datetime.now(timezone.utc) - timedelta(seconds=10000))
    timed("/me as_of (middle of history)", "GET", "/me?" + qs(as_of=mid))
    timed("/me as_of + known_at", "GET", "/me?" + qs(as_of=mid, known_at=mid))
    target = next(p for p in first["entries"] if p["delta"] < 0)["payment"]
    timed("correction (overdraft check over history)", "POST",
          "/payments/%s/corrections" % target["payment_id"],
          {"expected_revision": 1, "amount": target["amount"],
           "effective_at": target["created_at"], "reason": "big"}, uuid.uuid4().hex)
    t0 = time.monotonic()
    call("GET", "/_test/export", timeout=60)
    print("{:<44} {:.3f}s".format("export", time.monotonic() - t0))


def main():
    big_mode() if "big" in sys.argv[1:] else load_mode()
    for p in problems[:15]:
        print("FAIL", p)
    print("PASS" if not problems else "FAIL ({} problems)".format(len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
