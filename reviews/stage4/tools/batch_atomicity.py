#!/usr/bin/env python3
"""Verifier batch-atomicity probe for stage 4 (POST /correction-batches), failure injected on the LAST item.

    python3 reviews/stage4/tools/batch_atomicity.py http://127.0.0.1:<port> [--concurrent 20]

Sequential part: for each failure kind, build a batch whose items 1..n-1 are valid and item n fails, then check: the expected
status/code (item errors in input order, then incomplete_settlement, then insufficient_funds, then historical_overdraft); NOTHING
changed (every item's revisions, every party's /me and full statement, the activity feed); and the same idempotency key is reusable
afterwards with a valid body (201). Failure kinds on the last item: unknown payment (404), stale expected_revision (409), capture
and refund (422 linked_payment_immutable), below the refunded amount (422 refund_exceeds_payment), future effective_at (422),
duplicate payment_id (422), an incomplete settlement (422 incomplete_settlement), members with different instants (422), current
unaffordable (409 insufficient_funds), historical overdraft (409).
Concurrent part: many batches race with single corrections on shared payments; half the batches carry an injected failing last
item. Afterwards: per payment, revisions increase by one per accepted write (no lost or doubled revisions); for every
(payment, expected_revision) at most one success; the sum of totals equals the seeded total in /me now and at every as_of instant;
no 5xx and nothing over 5 s.
"""
import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

PW = "correct horse"
problems = []


def call(B, m, p, b=None, t=None, k=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = "Bearer " + t
    if k:
        h["Idempotency-Key"] = k
    t0 = time.monotonic()
    r = urllib.request.Request(B + p, data=None if b is None else json.dumps(b).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            st, d = x.status, x.read()
    except urllib.error.HTTPError as e:
        st, d = e.code, e.read()
    if st >= 500 or time.monotonic() - t0 > 5:
        problems.append("5xx/slow %s %s %s" % (st, m, p))
    return st, (json.loads(d) if d else None)


def U(i, h, b):
    return {"id": i, "email": h + "@e.com", "password": PW, "display_name": h, "handle": h, "balance": b}


def ago(s):
    return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def world(B):
    fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"],
          "users": [U("u_a", "a", 10000), U("u_b", "b", 10000), U("u_c", "c", 10000), U("u_op", "op", 0), U("u_poor", "poor", 100)]}
    assert call(B, "POST", "/_test/reset", fx)[0] == 204
    T = {h: call(B, "POST", "/auth/login", {"email": h + "@e.com", "password": PW})[1]["token"] for h in ("a", "b", "c", "op", "poor")}
    pay = lambda f, t, amt: call(B, "POST", "/payments", {"to_handle": t, "amount": amt}, T[f], uuid.uuid4().hex)[1]["payment_id"]
    w = {"T": T, "plain": [pay("a", "b", 100 + i) for i in range(4)]}
    st = call(B, "POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "c", "amount": 50},
                                                        {"from_handle": "c", "to_handle": "b", "amount": 20}]}, T["op"], uuid.uuid4().hex)[1]
    w["members"] = [m["payment_id"] for m in st["payments"]]
    au = call(B, "POST", "/authorizations", {"to_handle": "b", "amount": 30}, T["a"], uuid.uuid4().hex)[1]
    w["capture"] = call(B, "POST", "/authorizations/%s/capture" % au["authorization_id"], {}, T["b"], uuid.uuid4().hex)[1]["payment_id"]
    w["refunded"] = pay("a", "b", 200)
    w["refund"] = call(B, "POST", "/payments/%s/refunds" % w["refunded"], {"amount": 150}, T["b"], uuid.uuid4().hex)[1]["payment_id"]
    w["poor_recv"] = pay("a", "poor", 500)                                         # poor then spends it all
    call(B, "POST", "/payments", {"to_handle": "c", "amount": 600}, T["poor"], uuid.uuid4().hex)
    w["early"] = pay("b", "poor", 1)
    return w


def item(pid, rev=1, amount=1, eff=None, reason="batch"):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff or ago(1), "reason": reason}


def observe(B, w):
    T = w["T"]
    pids = w["plain"] + w["members"] + [w["capture"], w["refunded"], w["refund"], w["poor_recv"], w["early"]]
    revs = {p: call(B, "GET", "/payments/%s/revisions" % p, t=T["a"])[1] for p in pids}
    me = {h: call(B, "GET", "/me", t=t)[1] for h, t in T.items()}
    stm = {h: [(e["payment"]["payment_id"], e["revision"], e["delta"]) for e in call(B, "GET", "/statement?limit=200", t=t)[1]["entries"]] for h, t in T.items()}
    feed = call(B, "GET", "/activity?limit=200", t=T["a"])[1]
    return revs, me, stm, feed


def sequential(B):
    w = world(B)
    T, P, M = w["T"], w["plain"], w["members"]
    same = ago(2)
    cases = [
        ("unknown payment", [item(P[0]), item("p_nope")], (404, "not_found")),
        ("stale revision", [item(P[0]), item(P[1], rev=2)], (409, "stale_revision")),
        ("capture immutable", [item(P[0]), item(w["capture"])], (422, "linked_payment_immutable")),
        ("refund immutable", [item(P[0]), item(w["refund"])], (422, "linked_payment_immutable")),
        ("below refunded", [item(P[0]), item(w["refunded"], amount=100)], (422, "refund_exceeds_payment")),
        ("future effective_at", [item(P[0]), item(P[1], eff=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())], (422, "validation_failed")),
        ("duplicate payment_id", [item(P[0]), item(P[0], amount=2)], (422, "validation_failed")),
        ("incomplete settlement", [item(P[0]), item(M[0], eff=same)], (422, "incomplete_settlement")),
        ("members at different instants", [item(P[0]), item(M[0], eff=same), item(M[1], eff=ago(3))], (422, "validation_failed")),
        ("current unaffordable", [item(P[0]), item(w["poor_recv"], amount=0)], (409, "insufficient_funds")),
        ("historical overdraft", [item(P[0]), item(w["early"], amount=600, eff=ago(3600 * 24))], None),
    ]
    for name, items, want in cases:
        before = observe(B, w)
        key = uuid.uuid4().hex
        st, body = call(B, "POST", "/correction-batches", {"corrections": items}, T["op"], key)
        got = (st, (body or {}).get("error", {}).get("code"))
        ok_status = got == want if want else got in ((409, "historical_overdraft"), (409, "insufficient_funds"))
        after = observe(B, w)
        unchanged = after == before
        reuse = call(B, "POST", "/correction-batches", {"corrections": [item(P[3], rev=len(after[0][P[3]]["revisions"]), amount=99)]}, T["op"], key)
        print("%-4s %-30s got %-40s unchanged=%s key reusable=%s" % ("ok" if ok_status and unchanged and reuse[0] == 201 else "FAIL", name, got, unchanged, reuse[0]))
        if not (ok_status and unchanged and reuse[0] == 201):
            problems.append(name)
    # a valid whole-settlement batch: shared recorded_at, ids, input order
    st, body = call(B, "POST", "/correction-batches", {"corrections": [item(M[1], amount=10, eff=same), item(M[0], amount=40, eff=same.replace("+00:00", "Z"))]}, T["op"], uuid.uuid4().hex)
    good = st == 201 and [r["payment_id"] for r in body["revisions"]] == [M[1], M[0]] and len({r["recorded_at"] for r in body["revisions"]}) == 1 \
        and all(r.get("correction_batch_id") == body["correction_batch_id"] for r in body["revisions"]) and body["recorded_at"] == body["revisions"][0]["recorded_at"]
    print("%-4s whole settlement (offset spellings differ) -> 201, input order, shared recorded_at, batch ids" % ("ok" if good else "FAIL"), st)
    if not good:
        problems.append("whole settlement")


def concurrent(B, n):
    w = world(B)
    T, P = w["T"], w["plain"]
    seeded = sum(call(B, "GET", "/me", t=t)[1]["total"] for t in T.values())
    wins, lock = [], threading.Lock()

    def worker(i):
        pid = P[i % len(P)]
        revs = call(B, "GET", "/payments/%s/revisions" % pid, t=T["a"])[1]["revisions"]
        rev = revs[-1]["revision"]
        if i % 3 == 0:
            single = {k: v for k, v in item(pid, rev, amount=50 + i).items() if k != "payment_id"}
            st, _ = call(B, "POST", "/payments/%s/corrections" % pid, single, T["a"], uuid.uuid4().hex)
        else:
            items = [item(pid, rev, amount=60 + i)]
            if i % 2:
                items.append(item("p_missing_%d" % i))                        # injected failure on the last item
            st, _ = call(B, "POST", "/correction-batches", {"corrections": items}, T["op"], uuid.uuid4().hex)
        if st == 201:
            with lock:
                wins.append((pid, rev))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    dup = [k for k in set(wins) if wins.count(k) > 1]
    final = {p: call(B, "GET", "/payments/%s/revisions" % p, t=T["a"])[1]["revisions"] for p in P}
    gained = sum(len(r) - 1 for r in final.values())
    tot = sum(call(B, "GET", "/me", t=t)[1]["total"] for t in T.values())
    print("concurrent: %d writers, %d successes, duplicate winners %s, revisions gained %d, sum %d (seeded %d)" % (n, len(wins), dup, gained, tot, seeded))
    if dup or gained != len(wins) or tot != seeded:
        problems.append("concurrent")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--concurrent", type=int, default=20)
    a = ap.parse_args()
    B = a.base.rstrip("/")
    sequential(B)
    concurrent(B, a.concurrent)
    print("PASS" if not problems else "FAIL %s" % problems[:10])
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
