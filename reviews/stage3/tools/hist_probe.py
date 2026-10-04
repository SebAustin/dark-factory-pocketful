#!/usr/bin/env python3
"""Verifier concurrent historical-read probe for stage 3.

    HIST_SECONDS=30 python3 reviews/stage3/tools/hist_probe.py http://127.0.0.1:<port>

Writers (payments, corrections with expected_revision, authorizations and captures) run at the same time as readers:
  - /me?as_of=A&known_at=K for every user at one shared (A, K): sum of `total` over users must equal the seeded total,
    and for every user total == balance, available == total - held >= 0, held >= 0;
  - a frozen past view (K fixed before the load started) must return identical answers on every read;
  - /statement per user: opening + sum(delta) == closing, balance_after chains, ordering by (effective_at, payment id);
  - snapshot paging: page a snapshot with limit 3 while writes continue; every page must equal the same slice of the
    first full read of that snapshot, and opening, closing and has_more must stay consistent.
Afterwards (quiescent): the sum of current totals equals the seeded total, and a correction race with the same
expected_revision lets exactly one through.
Stdlib only. Exit 1 on any violation, any 5xx, or any response slower than 5 s.
"""
import json
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

B = sys.argv[1].rstrip("/")
SECONDS = float(os.environ.get("HIST_SECONDS", "30"))
USERS, SEED = 8, 50000
PW = "correct horse"
lock = threading.Lock()
problems, stats = [], {"reads": 0, "writes": 0, "slow": 0, "5xx": 0}


def call(method, path, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    t0 = time.monotonic()
    req = urllib.request.Request(B + path, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status, d = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, d = e.code, e.read()
    took = time.monotonic() - t0
    with lock:
        if status >= 500:
            stats["5xx"] += 1
            problems.append("5xx %s %s" % (method, path))
        if took > 5:
            stats["slow"] += 1
            problems.append("slow %.1fs %s %s" % (took, method, path))
    return status, (json.loads(d) if d else None)


def problem(text):
    with lock:
        if len(problems) < 200:
            problems.append(text)


def now():
    return datetime.now(timezone.utc).isoformat()


q = lambda v: urllib.parse.quote(v, safe="")


def setup():
    users = [{"id": "u%d" % i, "email": "u%d@e.com" % i, "password": PW, "display_name": "U%d" % i, "handle": "u%d" % i,
              "balance": SEED} for i in range(USERS)]
    assert call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users, "authorization_ttl_seconds": 3})[0] == 204
    return [call("POST", "/auth/login", {"email": "u%d@e.com" % i, "password": PW})[1]["token"] for i in range(USERS)]


def writer(tokens, deadline, payments):
    rng = random.Random()
    while time.monotonic() < deadline:
        a, b = rng.sample(range(USERS), 2)
        op = rng.random()
        if op < 0.45:
            s, p = call("POST", "/payments", {"to_handle": "u%d" % b, "amount": rng.randint(1, 900)}, tokens[a], uuid.uuid4().hex)
            if s == 201:
                with lock:
                    payments.append((p["payment_id"], a))
        elif op < 0.7 and payments:
            pid, sender = rng.choice(payments)
            s, revs = call("GET", "/payments/%s/revisions" % pid, tok=tokens[sender])
            if s == 200 and revs["revisions"]:
                last = revs["revisions"][-1]
                call("POST", "/payments/%s/corrections" % pid,
                     {"expected_revision": last["revision"], "amount": rng.randint(0, 900), "effective_at": now(), "reason": "probe"},
                     tokens[sender], uuid.uuid4().hex)
        elif op < 0.85:
            s, h = call("POST", "/authorizations", {"to_handle": "u%d" % b, "amount": rng.randint(1, 500)}, tokens[a], uuid.uuid4().hex)
            if s == 201 and rng.random() < 0.6:
                call("POST", "/authorizations/%s/capture" % h["authorization_id"], {"amount": rng.randint(1, h["amount"]), "final": rng.random() < 0.5},
                     tokens[b], uuid.uuid4().hex)
        with lock:
            stats["writes"] += 1


def check_me_view(tokens, as_of, known_at, frozen=None):
    qs = "?as_of=%s&known_at=%s" % (q(as_of), q(known_at))
    views = [call("GET", "/me" + qs, tok=t) for t in tokens]
    if any(s != 200 for s, _ in views):
        problem("me view status %s" % [s for s, _ in views])
        return None
    body = [v for _, v in views]
    for v in body:
        if v["balance"] != v["total"] or v["available"] != v["total"] - v["held"] or v["available"] < 0 or v["held"] < 0:
            problem("me view identities broken %s" % json.dumps(v)[:200])
    total = sum(v["total"] for v in body)
    if total != USERS * SEED:
        problem("sum of totals %d != %d at as_of=%s known_at=%s" % (total, USERS * SEED, as_of, known_at))
    return [(v["total"], v["held"]) for v in body]


def check_statement(tok, label):
    s, b = call("GET", "/statement?limit=200", tok=tok)
    if s != 200:
        problem("%s statement %s" % (label, s))
        return
    run, order = b["opening_balance"], []
    for e in b["entries"]:
        run += e["delta"]
        if e["balance_after"] != run:
            problem("%s balance_after chain broken" % label)
            break
        order.append((e.get("effective_at") or e["payment"]["created_at"], e["payment"]["payment_id"]))
    if not b["has_more"] and run != b["closing_balance"]:
        problem("%s opening+deltas %d != closing %d" % (label, run, b["closing_balance"]))
    if [datetime.fromisoformat(t) for t, _ in order] != sorted(datetime.fromisoformat(t) for t, _ in order):
        problem("%s entries not ordered by effective_at" % label)


def check_snapshot_paging(tok, label):
    s, first = call("GET", "/statement?limit=200", tok=tok)
    if s != 200 or "snapshot" not in first:
        problem("%s no snapshot (%s)" % (label, s))
        return
    full = first["entries"]
    snap, off = first["snapshot"], 0
    while True:
        s, page = call("GET", "/statement?snapshot=%s&limit=3&offset=%d" % (snap, off), tok=tok)
        if s != 200:
            problem("%s snapshot page %s" % (label, s))
            return
        if page["entries"] != full[off:off + 3] or page["opening_balance"] != first["opening_balance"] \
                or page["closing_balance"] != first["closing_balance"] or page["has_more"] != (off + 3 < len(full)):
            problem("%s snapshot page at offset %d differs from the frozen read" % (label, off))
            return
        off += 3
        if off >= len(full):
            return


def reader(tokens, deadline, frozen_k):
    rng = random.Random()
    frozen = check_me_view(tokens, frozen_k, frozen_k)
    while time.monotonic() < deadline:
        r = rng.random()
        if r < 0.4:
            k = now()
            check_me_view(tokens, k, k)
        elif r < 0.55:
            if check_me_view(tokens, frozen_k, frozen_k) != frozen:
                problem("frozen past view changed (known_at=%s)" % frozen_k)
        elif r < 0.8:
            i = rng.randrange(USERS)
            check_statement(tokens[i], "u%d" % i)
        else:
            i = rng.randrange(USERS)
            check_snapshot_paging(tokens[i], "u%d" % i)
        with lock:
            stats["reads"] += 1


def correction_race(tokens):
    s, p = call("POST", "/payments", {"to_handle": "u1", "amount": 100}, tokens[0], uuid.uuid4().hex)
    results = []

    def go(n):
        results.append(call("POST", "/payments/%s/corrections" % p["payment_id"],
                            {"expected_revision": 1, "amount": 50 + n, "effective_at": now(), "reason": "race %d" % n},
                            tokens[0], uuid.uuid4().hex)[0])
    threads = [threading.Thread(target=go, args=(n,)) for n in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    if results.count(201) != 1 or any(r not in (201, 409) for r in results):
        problem("correction race: %s" % sorted(results))


def main():
    tokens = setup()
    payments = []
    for i in range(USERS):                                     # some history before the frozen instant
        call("POST", "/payments", {"to_handle": "u%d" % ((i + 1) % USERS), "amount": 100}, tokens[i], uuid.uuid4().hex)
    time.sleep(1.1)
    frozen_k = now()
    time.sleep(1.1)
    deadline = time.monotonic() + SECONDS
    threads = [threading.Thread(target=writer, args=(tokens, deadline, payments)) for _ in range(20)] + \
              [threading.Thread(target=reader, args=(tokens, deadline, frozen_k)) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    time.sleep(4)                                             # every 3 s hold has expired
    k = now()
    check_me_view(tokens, k, k)
    correction_race(tokens)
    print("reads %(reads)d writes %(writes)d slow %(slow)d 5xx %(5xx)d" % stats)
    for p_ in problems[:20]:
        print("PROBLEM", p_)
    print("PASS" if not problems else "FAIL (%d problems)" % len(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
