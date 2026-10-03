"""Verifier probes for S2.3 (authorize, list) and S2.4 (capture, void).

    python3 reviews/stage2/tools/probe_s23_s24.py http://127.0.0.1:<port>
"""
import concurrent.futures as cf
import json
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

B = sys.argv[1]
_k = iter(range(10 ** 9))


def call(method, path, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(B + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = r.read()
            return r.status, json.loads(d) if d else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def c(r):
    return (r[0], r[1]["error"]["code"]) if r[0] >= 400 else r[0]


def K():
    return "k%d" % next(_k)


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h,
                     "handle": h, "balance": b}


def reset(ttl=None, auths=()):
    fx = {"currency": "EUR", "minor_units": 2,
          "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 2500), U("u_cy", "cy", 0)],
          "authorizations": list(auths)}
    if ttl is not None:
        fx["authorization_ttl_seconds"] = ttl
    assert call("POST", "/_test/reset", fx)[0] == 204
    return {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"]
            for h in ("ada", "bob", "cy")}


def me(t):
    m = call("GET", "/me", tok=t)[1]
    return m["total"], m["available"], m["held"]


def total_sum(T):
    return sum(me(t)[0] for t in T.values())


AUTH = lambda T, body, who="ada", key=None: call("POST", "/authorizations", body, T[who], key or K())
CAP = lambda T, aid, body, who="bob", key=None: call("POST", "/authorizations/%s/capture" % aid, body, T[who], key or K())
VOID = lambda T, aid, who="ada": call("POST", "/authorizations/%s/void" % aid, None, T[who])
out = {}

# ---- S2.3 authorize
T = reset()
r = AUTH(T, {"to_handle": "bob", "amount": 2000, "note": "deposit", "visibility": "private"}, key="a1")
a = r[1]
out["201 keys"] = (r[0], sorted(a))
created = datetime.fromisoformat(a["created_at"]); expires = datetime.fromisoformat(a["expires_at"])
out["expires = created + 600"] = (expires - created).total_seconds()
out["defaults"] = (lambda x: (x["note"], x["visibility"], x["status"], x["captured_amount"], x["remaining_amount"], x["payment_id"]))(AUTH(T, {"to_handle": "bob", "amount": 1})[1])
out["me after holds"] = me(T["ada"])
out["replay / reuse"] = [(lambda x: (x[0], x[1] == a))(AUTH(T, {"to_handle": "bob", "amount": 2000, "note": "deposit", "visibility": "private"}, key="a1")),
                         c(AUTH(T, {"to_handle": "bob", "amount": 2001}, key="a1"))]
out["errors"] = {
    "available below": c(AUTH(T, {"to_handle": "bob", "amount": 7000})),
    "amount 0 / 1e9+1 / 1.5 / '5' / true": [c(AUTH(T, {"to_handle": "bob", "amount": v})) for v in (0, 1000000001, 1.5, "5", True)],
    "self": c(AUTH(T, {"to_handle": "ada", "amount": 1})),
    "note 201": c(AUTH(T, {"to_handle": "bob", "amount": 1, "note": "x" * 201})),
    "visibility": c(AUTH(T, {"to_handle": "bob", "amount": 1, "visibility": "friends"})),
    "unknown": c(AUTH(T, {"to_handle": "zzz", "amount": 1})),
    "no key": c(call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, T["ada"])),
    "no token": c(call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, None, K())),
}
out["not in activity (ada, bob)"] = [len(call("GET", "/activity", tok=T[h])[1]["payments"]) for h in ("ada", "bob")]
L = lambda who, q="": call("GET", "/authorizations" + q, tok=T[who])
out["list ada / bob / cy"] = [len(L(h)[1]["authorizations"]) for h in ("ada", "bob", "cy")]
out["list direction/status"] = [len(L("ada", "?direction=incoming")[1]["authorizations"]), len(L("bob", "?direction=incoming")[1]["authorizations"]),
                                len(L("ada", "?status=open")[1]["authorizations"]), len(L("ada", "?status=voided")[1]["authorizations"])]
out["list order newest first"] = [x["authorization_id"] for x in L("ada")[1]["authorizations"]]
out["list 422s / paging"] = [c(L("ada", q)) for q in ("?direction=x", "?status=pending", "?limit=0", "?offset=-1")] + [(lambda x: (len(x[1]["authorizations"]), x[1]["has_more"]))(L("ada", "?limit=1"))]
# concurrency: 30 x 1000 on a 10000 wallet
T = reset()
with cf.ThreadPoolExecutor(30) as ex:
    res = list(ex.map(lambda i: c(AUTH(T, {"to_handle": "bob", "amount": 1000})), range(30)))
out["30 concurrent 1000-holds"] = (Counter(map(str, res)), me(T["ada"]), total_sum(T))

# ---- clock expiry (ttl 2 s)
T = reset(ttl=2)
e = AUTH(T, {"to_handle": "bob", "amount": 600})[1]["authorization_id"]
out["ttl2 before"] = me(T["ada"])
time.sleep(3)
out["ttl2 after (no request between)"] = (me(T["ada"]), [x["status"] for x in L("ada", "?status=expired")[1]["authorizations"]],
                                         len(L("ada", "?status=open")[1]["authorizations"]))
out["capture expired / void expired"] = [c(CAP(T, e, {})), c(VOID(T, e))]

# ---- S2.4 capture
T = reset()
aid = AUTH(T, {"to_handle": "bob", "amount": 2000, "note": "n", "visibility": "private"})[1]["authorization_id"]
p = CAP(T, aid, {"amount": 1500}, key="c1")
out["partial final 1500/2000"] = (p[0], p[1]["amount"], p[1]["authorization_id"] == aid, p[1]["request_id"], p[1]["note"], p[1]["visibility"], sorted(p[1]))
out["after partial final: ada / bob"] = (me(T["ada"]), me(T["bob"]))
out["replay {amount:1500} / reuse {} / second capture"] = [(lambda x: (x[0], x[1] == p[1]))(CAP(T, aid, {"amount": 1500}, key="c1")),
                                                           c(CAP(T, aid, {}, key="c1")), c(CAP(T, aid, {}))]
st = [x for x in L("ada")[1]["authorizations"] if x["authorization_id"] == aid][0]
out["auth after capture"] = (st["status"], st["captured_amount"], st["remaining_amount"], st["payment_id"] == p[1]["payment_id"])
out["capture in feeds (bob, ada, cy)"] = [any(x["payment_id"] == p[1]["payment_id"] for x in call("GET", "/activity", tok=T[h])[1]["payments"]) for h in ("bob", "ada", "cy")]
aid = AUTH(T, {"to_handle": "bob", "amount": 1000})[1]["authorization_id"]
chain = [CAP(T, aid, {"amount": 300, "final": False}), CAP(T, aid, {"amount": 200, "final": False})]
st = [x for x in L("bob")[1]["authorizations"] if x["authorization_id"] == aid][0]
out["nonfinal 300+200"] = (st["status"], st["captured_amount"], st["remaining_amount"], me(T["ada"])[2])
out["exceeds remainder 501 / amount 0 / 'x' / final 'no'"] = [c(CAP(T, aid, {"amount": 501, "final": False})), c(CAP(T, aid, {"amount": 0})),
                                                               c(CAP(T, aid, {"amount": "x"})), c(CAP(T, aid, {"final": "no"}))]
last = CAP(T, aid, {"final": False})
st = [x for x in L("bob")[1]["authorizations"] if x["authorization_id"] == aid][0]
out["remainder with final:false closes"] = (last[1]["amount"], st["status"], st["remaining_amount"], st["payment_ids"] == [chain[0][1]["payment_id"], chain[1][1]["payment_id"], last[1]["payment_id"]], st["payment_id"] == last[1]["payment_id"])
aid = AUTH(T, {"to_handle": "bob", "amount": 1000})[1]["authorization_id"]
CAP(T, aid, {"amount": 400, "final": False})
held_before = me(T["ada"])[2]
v = VOID(T, aid)
out["void after partial"] = (v[0], v[1]["status"], v[1]["captured_amount"], v[1]["remaining_amount"], len(v[1]["payment_ids"]), held_before, me(T["ada"])[2])
out["void twice / capture after void"] = [(lambda x: (x[0], x[1] == v[1]))(VOID(T, aid)), c(CAP(T, aid, {}))]
aid = AUTH(T, {"to_handle": "bob", "amount": 10})[1]["authorization_id"]
out["permissions: capture by payer / third; void by receiver / third"] = [c(CAP(T, aid, {}, who="ada")), c(CAP(T, aid, {}, who="cy")), c(VOID(T, aid, who="bob")), c(VOID(T, aid, who="cy"))]
CAP(T, aid, {})
out["void captured / unknown / no key on capture"] = [c(VOID(T, aid)), c(VOID(T, "a_zzz")), c(CAP(T, "a_zzz", {})),
                                                      c(call("POST", "/authorizations/%s/capture" % aid, {}, T["bob"]))]
out["sum of totals after S2.4 flow"] = total_sum(T)
# concurrency: 30 x 300 captures on 2000
T = reset()
aid = AUTH(T, {"to_handle": "bob", "amount": 2000})[1]["authorization_id"]
with cf.ThreadPoolExecutor(30) as ex:
    res = list(ex.map(lambda i: c(CAP(T, aid, {"amount": 300, "final": False})), range(30)))
st = [x for x in L("ada")[1]["authorizations"] if x["authorization_id"] == aid][0]
out["30 concurrent 300-captures on 2000"] = (Counter(map(str, res)), st["captured_amount"], me(T["ada"]), total_sum(T))
# same key x30
aid = AUTH(T, {"to_handle": "bob", "amount": 100})[1]["authorization_id"]
with cf.ThreadPoolExecutor(30) as ex:
    res = list(ex.map(lambda i: CAP(T, aid, {}, key="same"), range(30)))
out["30 same-key captures"] = (Counter(r[0] for r in res), len({json.dumps(r[1], sort_keys=True) for r in res}), total_sum(T))
for k2, v2 in out.items():
    print(k2, "->", v2)
