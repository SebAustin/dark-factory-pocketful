#!/usr/bin/env python3
"""S1.8 soak against a running container (stdlib only, not part of unittest discovery).

    TARGET_URL=http://127.0.0.1:18200 SOAK_SECONDS=60 python3 stage-1/tests/soak.py

Checks the stage-1 runtime limits and invariants: a 1000-user reset with distinct passwords
inside 10 s; 50 concurrent signups and logins inside 5 s each; then SOAK_SECONDS of 50 in-flight
mixed writes and reads (payments, requests, pay, decline, cancel, activity, me). Fails on any
5xx, any response over 5 s, a negative balance, or a changed balance total. Exit 0 = pass.
"""
import http.client
import json
import os
import random
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

TARGET = urlsplit(os.environ.get("TARGET_URL", "http://127.0.0.1:18200"))
SECONDS = float(os.environ.get("SOAK_SECONDS", "60"))
WORKERS = 50
USERS = 20
START_BALANCE = 5000
LIMIT_S = 5.0

lat, fails, statuses = [], [], {}
guard = threading.Lock()


local = threading.local()


def _conn(timeout):
    conn = getattr(local, "conn", None)
    if conn is None:
        conn = local.conn = http.client.HTTPConnection(TARGET.hostname, TARGET.port,
                                                       timeout=timeout)
    return conn


def call(method, path, body=None, token=None, key=None, timeout=12):
    """One keep-alive connection per thread (a new socket per call exhausts client ports)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    started = time.monotonic()
    try:
        conn = _conn(timeout)
        conn.request(method, path, None if body is None else json.dumps(body), headers)
        r = conn.getresponse()
        raw = r.read()
    except (OSError, http.client.HTTPException) as exc:
        local.conn = None
        with guard:
            fails.append("transport {} {} {!r}".format(method, path, exc))
        return 0, None
    took = time.monotonic() - started
    with guard:
        lat.append(took)
        statuses[r.status] = statuses.get(r.status, 0) + 1
        if r.status >= 500:
            fails.append("5xx {} {} {}".format(method, path, raw[:200]))
        if took > LIMIT_S and path != "/_test/reset":
            fails.append("slow {:.2f}s {} {}".format(took, method, path))
    return r.status, (json.loads(raw) if raw else None)


def burst(fn, n):
    out = [None] * n
    threads = [threading.Thread(target=lambda i=i: out.__setitem__(i, fn(i))) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def check_big_reset():
    users = [{"id": "b%d" % i, "email": "b%d@e.com" % i, "password": "pw-%d-xyz" % i,
              "display_name": "B", "handle": "b%d" % i, "balance": 1} for i in range(1000)]
    started = time.monotonic()
    status, _ = call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                                              "users": users})
    took = time.monotonic() - started
    print("reset 1000 distinct-password users: {} in {:.2f}s".format(status, took))
    if status != 204 or took > 10:
        fails.append("big reset {} {:.2f}s".format(status, took))


def check_auth_burst():
    burst(lambda i: call("POST", "/auth/signup", {"email": "s%d@x.com" % i,
                                                  "password": "correct horse",
                                                  "display_name": "S"}), 50)
    burst(lambda i: call("POST", "/auth/login", {"email": "s%d@x.com" % i,
                                                 "password": "correct horse"}), 50)
    print("50 signups + 50 logins: max latency so far {:.2f}s".format(max(lat)))


def seed():
    users = [{"id": "u%d" % i, "email": "u%d@e.com" % i, "password": "correct horse",
              "display_name": "U%d" % i, "handle": "u%d" % i, "balance": START_BALANCE}
             for i in range(USERS)]
    assert call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                                         "users": users})[0] == 204
    return [call("POST", "/auth/login", {"email": "u%d@e.com" % i,
                                         "password": "correct horse"})[1]["token"]
            for i in range(USERS)]


def worker(tokens, deadline, request_ids):
    rng = random.Random()
    while time.monotonic() < deadline:
        a, b = rng.sample(range(USERS), 2)
        op = rng.random()
        if op < 0.35:
            call("POST", "/payments", {"to_handle": "u%d" % b, "amount": rng.randint(1, 900),
                                       "visibility": rng.choice(["public", "private"])},
                 tokens[a], uuid.uuid4().hex)
        elif op < 0.55:
            s, body = call("POST", "/requests", {"payer_handle": "u%d" % b,
                                                 "amount": rng.randint(1, 900)},
                           tokens[a], uuid.uuid4().hex)
            if s == 201:
                with guard:
                    request_ids.append((body["request_id"], a, b))
        elif op < 0.75 and request_ids:
            rid, req, payer = rng.choice(request_ids)
            verb = rng.choice(["pay", "pay", "decline", "cancel"])
            who = req if verb == "cancel" else payer
            call("POST", "/requests/%s/%s" % (rid, verb), {}, tokens[who],
                 uuid.uuid4().hex if verb == "pay" else None)
        elif op < 0.9:
            call("GET", "/activity?limit=50", token=tokens[a])
        else:
            s, me = call("GET", "/me", token=tokens[a])
            if s == 200 and me["balance"] < 0:
                fails.append("negative balance " + str(me))


def mixed_load():
    tokens = seed()
    request_ids = []
    deadline = time.monotonic() + SECONDS
    threads = [threading.Thread(target=worker, args=(tokens, deadline, request_ids))
               for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    balances = [call("GET", "/me", token=t)[1]["balance"] for t in tokens]
    if sum(balances) != USERS * START_BALANCE or min(balances) < 0:
        fails.append("invariant broken: sum {} min {}".format(sum(balances), min(balances)))


def main():
    check_big_reset()
    check_auth_burst()
    lat.clear()
    started = time.monotonic()
    mixed_load()
    ordered = sorted(lat)
    p50, p99 = ordered[len(ordered) // 2], ordered[int(len(ordered) * 0.99)]
    print("mixed load: {} requests in {:.0f}s, p50 {:.3f}s p99 {:.3f}s max {:.3f}s, statuses {}"
          .format(len(ordered), time.monotonic() - started, p50, p99, ordered[-1],
                  dict(sorted(statuses.items()))))
    for f in fails[:10]:
        print("FAIL", f)
    print("PASS" if not fails else "FAIL ({} problems)".format(len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
