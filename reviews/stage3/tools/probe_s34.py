"""Verifier oracle for S3.4 corrections: predict 201 / 409 insufficient_funds / 409 historical_overdraft from the spec text and
the parties' statements, for many random corrections, and compare. Also checks that refusals change nothing, and that the sum of
totals holds and statements chain after every accepted correction.

    python3 reviews/stage3/tools/probe_s34.py http://127.0.0.1:<port> [n=150]
"""
import json
import random
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

B = sys.argv[1].rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 150
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def call(m, p, b=None, t=None, k=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = "Bearer " + t
    if k:
        h["Idempotency-Key"] = k
    r = urllib.request.Request(B + p, data=None if b is None else json.dumps(b).encode(), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=15) as x:
            d = x.read()
            return x.status, (json.loads(d) if d else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


us = lambda s: (datetime.fromisoformat(s.replace("Z", "+00:00")) - EPOCH) // timedelta(microseconds=1)
iso = lambda u: (EPOCH + timedelta(microseconds=u)).isoformat(timespec="microseconds")
U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
rng = random.Random(11)
users = ("a", "b", "c")
assert call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_" + h, h, 300) for h in users]})[0] == 204
T = {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"] for h in users}
start = None
pays = []                                                  # (pid, sender, receiver)
for i in range(30):
    s, r = rng.sample(users, 2)
    st, p = call("POST", "/payments", {"to_handle": r, "amount": rng.randint(1, 80)}, T[s], "p%d" % i)
    if st == 201:
        pays.append((p["payment_id"], s, r))
        start = start or us(p["created_at"])


def history(h):
    """(opening, [(instant, delta, pid)]) from the full statement (latest revisions)."""
    st, b = call("GET", "/statement?limit=200", t=T[h])
    assert st == 200 and not b["has_more"]
    return b["opening_balance"], [(us(e["effective_at"]), e["delta"], e["payment"]["payment_id"]) for e in b["entries"]], b


def nonneg(opening, moves):
    by = {}
    for t, d in moves:
        by[t] = by.get(t, 0) + d
    run = opening
    if run < 0:
        return False
    for t in sorted(by):
        run += by[t]
        if run < 0:
            return False
    return True


counts, problems = {}, []
for i in range(N):
    pid, s, r = rng.choice(pays)
    revs = call("GET", "/payments/%s/revisions" % pid, t=T[s])[1]["revisions"]
    cur = revs[-1]
    now_us = us(datetime.now(timezone.utc).isoformat())
    new_amt = rng.choice([0, cur["amount"] // 2, cur["amount"] + rng.randint(1, 150), rng.randint(0, 300)])
    eff = rng.randint(start - 2_000_000, now_us - 1000)
    hist = {h: history(h) for h in (s, r)}
    me = {h: call("GET", "/me", t=T[h])[1] for h in (s, r)}
    diff = new_amt - cur["amount"]
    debited = s if diff > 0 else r
    if diff and me[debited]["available"] < abs(diff):
        want = (409, "insufficient_funds")
    else:
        ok = True
        for h in (s, r):
            opening, entries, _ = hist[h]
            moves = [(t, d) for t, d, p in entries if p != pid]
            moves.append((eff, (-new_amt if h == s else new_amt)))
            ok &= nonneg(opening, moves)
        want = (201, None) if ok else (409, "historical_overdraft")
    before = {h: (me[h]["total"], hist[h][2]["entries"]) for h in (s, r)}
    st, body = call("POST", "/payments/%s/corrections" % pid,
                    {"expected_revision": cur["revision"], "amount": new_amt, "effective_at": iso(eff), "reason": "oracle %d" % i}, T[s], "c%d" % i)
    got = (st, (body or {}).get("error", {}).get("code") if st != 201 else None)
    counts[got] = counts.get(got, 0) + 1
    if got != want:
        problems.append(("predict", i, pid, got, want))
    if st != 201:
        after = {h: (call("GET", "/me", t=T[h])[1]["total"], history(h)[2]["entries"]) for h in (s, r)}
        if after != before:
            problems.append(("refusal changed state", i, pid))
    else:
        if body["revision"] != cur["revision"] + 1 or us(body["recorded_at"]) <= us(cur["recorded_at"]):
            problems.append(("revision/recorded_at", i, body))
    tot = sum(call("GET", "/me", t=T[h])[1]["total"] for h in users)
    if tot != 900:
        problems.append(("sum", i, tot))
print("corrections attempted:", N, "outcomes:", counts)
print("problems:", len(problems))
for p_ in problems[:10]:
    print("  ", p_)
# historical views stay consistent after all the corrections
pts = sorted({t for h in users for t, _, _ in history(h)[1]})
bad = [t for t in pts[::max(1, len(pts) // 25)] if sum(call("GET", "/me?as_of=%s" % urllib.parse.quote(iso(t), safe=""), t=T[h])[1]["total"] for h in users) != 900]
print("as_of views with sum != 900:", len(bad))
