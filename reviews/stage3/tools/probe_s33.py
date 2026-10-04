"""Verifier probe for S3.3 (GET /statement + snapshots).

    python3 reviews/stage3/tools/probe_s33.py http://127.0.0.1:<port>

Cross-checks statements against GET /me (S3.2, accepted): opening == /me as_of (from − 1 µs), closing == /me as_of (to − 1 µs),
entries == the caller's payments with created_at in [from, to) ordered by (instant, payment id), sent negative / received positive,
chained balance_after, every page equal to the same slice of the full window. It also covers snapshots frozen against new payments,
the 422/404 matrix, own-payments-only and same-instant ties.
"""
import json
import random
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

B = sys.argv[1].rstrip("/")
q = lambda s: urllib.parse.quote(s, safe="")
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


def us(s):
    return (datetime.fromisoformat(s.replace("Z", "+00:00")) - EPOCH) // timedelta(microseconds=1)


def iso(u):
    return (EPOCH + timedelta(microseconds=u)).isoformat(timespec="microseconds")


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
tie = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
fx = {"currency": "EUR", "minor_units": 2, "users": [U("u_a", "a", 5000), U("u_b", "b", 5000), U("u_c", "c", 5000)],
      "payments": [{"id": "p_9", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 9, "created_at": tie},
                   {"id": "p_10", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 10, "created_at": tie},
                   {"id": "p_bc", "from_user_id": "u_b", "to_user_id": "u_c", "amount": 77, "visibility": "public",
                    "created_at": tie}]}
assert call("POST", "/_test/reset", fx)[0] == 204
T = {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"] for h in "abc"}
rng = random.Random(7)
mine = [("p_9", us(tie), +9), ("p_10", us(tie), -10)]          # a's payments: id, instant, delta for a
for i in range(25):
    other = rng.choice("bc")
    if rng.random() < 0.5:
        p = call("POST", "/payments", {"to_handle": other, "amount": rng.randint(1, 90)}, T["a"], "a%d" % i)[1]
        mine.append((p["payment_id"], us(p["created_at"]), -p["amount"]))
    else:
        p = call("POST", "/payments", {"to_handle": "a", "amount": rng.randint(1, 90)}, T[other], "o%d" % i)[1]
        mine.append((p["payment_id"], us(p["created_at"]), p["amount"]))
    call("POST", "/payments", {"to_handle": "c" if other == "b" else "b", "amount": 1}, T[other], "x%d" % i)  # not a's
problems = []


def me_total(as_of_us):
    return call("GET", "/me?as_of=%s" % q(iso(as_of_us)), t=T["a"])[1]["total"]


def full(query):
    s, first = call("GET", "/statement?limit=200" + query, t=T["a"])
    return s, first


times = sorted(t for _, t, _ in mine)
windows = [(None, None), (times[0], times[-1]), (times[3], times[3]), (times[5], times[12]), (times[2] - 1, times[9] + 1),
           (us(tie), us(tie) + 1), (times[-1] + 1, None)]
for frm, to in windows:
    qs = ("&from=%s" % q(iso(frm)) if frm is not None else "") + ("&to=%s" % q(iso(to)) if to is not None else "")
    s, b = full(qs)
    if s != 200:
        problems.append(("status", frm, to, s, b))
        continue
    lo = frm if frm is not None else -10 ** 18
    hi = to if to is not None else 10 ** 18
    want = sorted([(t, pid, d) for pid, t, d in mine if lo <= t < hi], key=lambda x: (x[0], x[1]))
    got = [(us(e["effective_at"]), e["payment"]["payment_id"], e["delta"]) for e in b["entries"]]
    if got != want:
        problems.append(("entries", frm, to, got[:4], want[:4]))
    run = b["opening_balance"]
    for e in b["entries"]:
        run += e["delta"]
        if e["balance_after"] != run or e["payment"]["amount"] != abs(e["delta"]) or e["revision"] != 1 or e["recorded_at"] != e["effective_at"]:
            problems.append(("entry", e["payment"]["payment_id"]))
    if run != b["closing_balance"]:
        problems.append(("sum", frm, to))
    exp_open = me_total(frm - 1) if frm is not None else me_total(0)
    exp_close = me_total(to - 1) if to is not None else call("GET", "/me", t=T["a"])[1]["total"]
    if (b["opening_balance"], b["closing_balance"]) != (exp_open, exp_close):
        problems.append(("open/close vs /me", frm, to, (b["opening_balance"], b["closing_balance"]), (exp_open, exp_close)))
    # pages of the snapshot equal slices of the full read
    snap = b["snapshot"]
    for lim in (1, 4, 7):
        for off in range(0, len(b["entries"]) + 3, lim):
            s2, pg = call("GET", "/statement?snapshot=%s&limit=%d&offset=%d" % (snap, lim, off), t=T["a"])
            if s2 != 200 or pg["entries"] != b["entries"][off:off + lim] or pg["opening_balance"] != b["opening_balance"] \
                    or pg["closing_balance"] != b["closing_balance"] or pg["has_more"] != (off + lim < len(b["entries"])):
                problems.append(("page", frm, to, lim, off))
                break
print("windows checked:", len(windows), "problems:", len(problems))
for p_ in problems[:6]:
    print("  ", p_)
tie_order = [e["payment"]["payment_id"] for e in full("")[1]["entries"] if e["payment"]["created_at"] == tie or us(e["effective_at"]) == us(tie)]
print("same-instant tie ordered by id (p_10 < p_9):", tie_order == ["p_10", "p_9"], tie_order)
print("third-party public payment absent:", all(e["payment"]["payment_id"] != "p_bc" for e in full("")[1]["entries"]))
s, b0 = full("")
snap = b0["snapshot"]
call("POST", "/payments", {"to_handle": "b", "amount": 5}, T["a"], "after")
s, b1 = call("GET", "/statement?snapshot=%s&limit=200" % snap, t=T["a"])
print("snapshot frozen after a new payment:", b1["entries"] == b0["entries"] and b1["closing_balance"] == b0["closing_balance"],
      "fresh read sees it:", len(full("")[1]["entries"]) == len(b0["entries"]) + 1)
codes = {
    "snapshot+from": call("GET", "/statement?snapshot=%s&from=%s" % (snap, q(iso(times[0]))), t=T["a"])[0],
    "snapshot+to": call("GET", "/statement?snapshot=%s&to=" % snap, t=T["a"])[0],
    "snapshot+known_at": call("GET", "/statement?snapshot=%s&known_at=%s" % (snap, q(iso(times[0]))), t=T["a"])[0],
    "snapshot other user": call("GET", "/statement?snapshot=%s" % snap, t=T["b"])[0],
    "snapshot unknown": call("GET", "/statement?snapshot=nope", t=T["a"])[0],
    "from > to": full("&from=%s&to=%s" % (q(iso(times[5])), q(iso(times[1]))))[0],
    "bad from": full("&from=2026-09-24")[0], "empty to": full("&to=")[0], "limit 0": call("GET", "/statement?limit=0", t=T["a"])[0],
    "no token": call("GET", "/statement")[0], "unknown param ignored": full("&zz=1")[0],
}
print("codes:", codes)
call("POST", "/_test/reset", fx)
T2 = call("POST", "/auth/login", {"email": "a@e.com", "password": "correct horse"})[1]["token"]
print("snapshot from before reset -> 404:", call("GET", "/statement?snapshot=%s" % snap, t=T2)[0] == 404)
