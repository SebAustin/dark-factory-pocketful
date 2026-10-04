"""Verifier probe for S3.2 (GET /me as_of + known_at, historical holds) — an independent oracle.

    python3 reviews/stage3/tools/probe_s32.py http://127.0.0.1:<port>

Builds a timeline through the API (payments, a seeded past payment, holds captured nonfinal then final, voided, and expired by
the clock), records every server-assigned instant from the responses, then queries /me at T and K around every event
(t - 1 µs, t, t + 1 µs) and compares with balances and holds computed here from the spec text alone. Also: sum of totals over
users in every view, identities, echo, and invalid forms.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import product

B = sys.argv[1].rstrip("/")


def call(m, p, b=None, t=None, k=None, raw=False):
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


def kk(s):  # exact epoch key in seconds (Decimal, µs)
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    us = (d - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(microseconds=1)
    return Decimal(us) / 10 ** 6


def iso(k):
    return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(k * 10 ** 6))).isoformat(timespec="microseconds")


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
fx = {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 3,
      "users": [U("u_a", "a", 1000), U("u_b", "b", 200)],
      "payments": [{"id": "p_seed", "from_user_id": "u_b", "to_user_id": "u_a", "amount": 50, "created_at": past}]}
assert call("POST", "/_test/reset", fx)[0] == 204
T = {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"] for h in ("a", "b")}
pays, holds = [], []          # payments: (key, from, amount); holds: list of events (key, held_delta) + expires key
pays.append((kk(past), "b", 50))
p = call("POST", "/payments", {"to_handle": "b", "amount": 100}, T["a"], "p1")[1]
pays.append((kk(p["created_at"]), "a", 100))
time.sleep(0.05)
h1 = call("POST", "/authorizations", {"to_handle": "b", "amount": 300}, T["a"], "h1")[1]
c1 = call("POST", "/authorizations/%s/capture" % h1["authorization_id"], {"amount": 100, "final": False}, T["b"], "c1")[1]
c2 = call("POST", "/authorizations/%s/capture" % h1["authorization_id"], {"amount": 50}, T["b"], "c2")[1]
pays += [(kk(c1["created_at"]), "a", 100), (kk(c2["created_at"]), "a", 50)]
h1_events = [(kk(h1["created_at"]), 300), (kk(c1["created_at"]), -100), (kk(c2["created_at"]), -200)]
h2 = call("POST", "/authorizations", {"to_handle": "b", "amount": 200}, T["a"], "h2")[1]
v = call("POST", "/authorizations/%s/void" % h2["authorization_id"], None, T["a"])[1]
h2_events = [(kk(h2["created_at"]), 200), (kk(v["closed_at"]), -200)]
h3 = call("POST", "/authorizations", {"to_handle": "b", "amount": 70}, T["a"], "h3")[1]
h3_events = [(kk(h3["created_at"]), 70)]
hold_defs = [(h1_events, kk(h1["expires_at"])), (h2_events, kk(h2["expires_at"])), (h3_events, kk(h3["expires_at"]))]
time.sleep(3.5)                                         # h3 expires by the clock


def total(h, t, k):
    # current balances reconstructed: opening for seeded = fixture end - seeded effect; API payments after reset
    open_ = {"a": 1000 - 50, "b": 200 + 50}
    tot = open_[h]
    for when, frm, amt in pays:
        if when <= t and when <= k:
            tot += -amt if frm == h else amt
    return tot


def held(h, t, k):
    if h != "a":
        return 0
    s = 0
    for events, exp in hold_defs:
        created = events[0][0]
        if created > k or t < created or t >= exp:
            continue
        x = events[0][1] + sum(d for when, d in events[1:] if when <= k and when <= t)
        s += max(x, 0)
    return s


q = lambda s: urllib.parse.quote(s, safe="")
instants = sorted({e for e, _, _ in pays} | {w for ev, _ in hold_defs for w, _ in ev} | {x for _, x in hold_defs})
probe_points = sorted({i + d for i in instants for d in (Decimal("-0.000001"), Decimal(0), Decimal("0.000001"))})
bad, n = [], 0
for t, k in product(probe_points, probe_points[::3] + [probe_points[-1] + 3600]):
    views = {}
    for h in ("a", "b"):
        s, body = call("GET", "/me?as_of=%s&known_at=%s" % (q(iso(t)), q(iso(k))), t=T[h])
        views[h] = body
        n += 1
        want = (total(h, t, k), held(h, t, k))
        got = (body["total"], body["held"])
        if s != 200 or got != want or body["balance"] != body["total"] or body["available"] != body["total"] - body["held"] or body["available"] < 0:
            bad.append((h, iso(t), iso(k), got, want))
    if views["a"]["total"] + views["b"]["total"] != 1200:
        bad.append(("sum", iso(t), iso(k), views["a"]["total"] + views["b"]["total"]))
print("timeline views checked:", n, "mismatches:", len(bad))
for b_ in bad[:8]:
    print("  ", b_)
now_view = call("GET", "/me", t=T["a"])[1]
print("no params = stage-2 shape, current:", sorted(now_view) == sorted(["user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"]),
      now_view["total"] == total("a", Decimal(10 ** 12), Decimal(10 ** 12)), now_view["held"] == 0)
print("opening before everything:", call("GET", "/me?as_of=1970-01-01T00:00:00Z", t=T["a"])[1]["total"] == 950)
weird = ["2026-09-24T13:20:00.123456789+02:00", "2026-09-24t11:20:00z"]
print("echo verbatim:", [call("GET", "/me?as_of=%s&known_at=%s" % (q(w), q(w)), t=T["a"])[1].get("as_of") == w for w in weird])
for bad_v in ["", "2026-09-24", "2026-09-24T13:20:00", "now", "2026-02-30T00:00:00Z", "1727000000", "2026-09-24T13:20:00+2:00"]:
    r = [call("GET", "/me?%s=%s" % (p_, q(bad_v)), t=T["a"])[0] for p_ in ("as_of", "known_at")]
    if r != [422, 422]:
        print("  invalid", repr(bad_v), r)
print("invalid forms checked")
