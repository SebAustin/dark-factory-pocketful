"""Verifier probes for S2.2 (holds model) against a running stage-2 service.

    python3 reviews/stage2/tools/probe_s22.py http://127.0.0.1:<port> [http://127.0.0.1:<stage-1 port>]
The optional second URL is a running stage-1 service, used to check that a stage-1 export imports.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

B = sys.argv[1]
S1 = sys.argv[2] if len(sys.argv) > 2 else None


def call(method, path, body=None, tok=None, key=None, base=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    req = urllib.request.Request((base or B) + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = r.read()
            return r.status, json.loads(d) if d else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def c(r):
    return (r[0], r[1]["error"]["code"]) if r[0] >= 400 else r[0]


def ts(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h,
                     "handle": h, "balance": b}
A = lambda i, f, t, amt, st, exp, **k: {"id": i, "from_user_id": f, "to_user_id": t, "amount": amt,
                                        "status": st, "expires_at": exp, **k}


def fixture(auths, **extra):
    return {"currency": "EUR", "minor_units": 2, "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 2500),
                                                          U("u_op", "op", 0)],
            "settlement_operator_ids": ["u_op"], "authorizations": auths, **extra}


def login(h, base=None):
    return call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"}, base=base)[1]["token"]


out = {}
assert call("POST", "/_test/reset", fixture([A("a_1", "u_ada", "u_bob", 2000, "open", ts(3600)),
                                             A("a_2", "u_ada", "u_bob", 500, "voided", ts(3600)),
                                             A("a_3", "u_ada", "u_bob", 700, "open", ts(-3600))]))[0] == 204
ta, tb, to = login("ada"), login("bob"), login("op")
me = lambda t: call("GET", "/me", tok=t)[1]
out["me ada (open 2000; voided; past-open 700)"] = me(ta)
out["me bob"] = {k: me(tb)[k] for k in ("balance", "total", "available", "held")}
out["pay 8001 / 8000"] = [c(call("POST", "/payments", {"to_handle": "bob", "amount": 8001}, ta, "p1")),
                          c(call("POST", "/payments", {"to_handle": "bob", "amount": 8000}, ta, "p2"))]
p = call("POST", "/payments", {"to_handle": "ada", "amount": 1}, tb, "p3")[1]
out["payment has authorization_id null"] = ("authorization_id" in p, p.get("authorization_id"))
out["after: ada"] = {k: me(ta)[k] for k in ("balance", "total", "available", "held")}

call("POST", "/_test/reset", fixture([A("a_1", "u_ada", "u_bob", 2000, "open", ts(3600))]))
ta, tb, to = login("ada"), login("bob"), login("op")
rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 8001}, tb, "r1")[1]["request_id"]
out["request pay 8001 vs available 8000"] = c(call("POST", "/requests/%s/pay" % rq, {}, ta, "k"))
out["settlement net -8001 / -8000"] = [
    c(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 8001}]}, to, "s1")),
    c(call("POST", "/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 8000}]}, to, "s2"))]

base = fixture([])
call("POST", "/_test/reset", base)
before = call("GET", "/_test/export")[1]
bad = {
    "holds > balance": fixture([A("a_1", "u_ada", "u_bob", 6000, "open", ts(3600)),
                                A("a_2", "u_ada", "u_bob", 4001, "open", ts(7200))]),
    "ttl 0": fixture([], authorization_ttl_seconds=0), "ttl -1": fixture([], authorization_ttl_seconds=-1),
    "ttl 1.5": fixture([], authorization_ttl_seconds=1.5), "ttl '600'": fixture([], authorization_ttl_seconds="600"),
    "ttl true": fixture([], authorization_ttl_seconds=True), "ttl null": fixture([], authorization_ttl_seconds=None),
    "status bogus": fixture([A("a_1", "u_ada", "u_bob", 1, "pending", ts(3600))]),
    "no expires_at": fixture([{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "status": "open"}]),
    "unknown user": fixture([A("a_1", "u_ada", "u_zz", 1, "open", ts(3600))]),
    "authorizations not list": fixture({}),
}
out["fixture 422s"] = {k: c(call("POST", "/_test/reset", v)) for k, v in bad.items()}
out["state unchanged after 422s"] = call("GET", "/_test/export")[1]["state"]["users"] == before["state"]["users"]
out["holds == balance ok"] = c(call("POST", "/_test/reset", fixture([A("a_1", "u_ada", "u_bob", 10000, "open", ts(3600))])))
out["ttl 1.0 / omitted"] = [c(call("POST", "/_test/reset", fixture([], authorization_ttl_seconds=1.0))),
                            c(call("POST", "/_test/reset", fixture([])))]
out["expired-in-past held open-ignored"] = None

# expiry with no request at the deadline
call("POST", "/_test/reset", fixture([A("a_x", "u_ada", "u_bob", 3000, "open", ts(3))]))
ta = login("ada")
out["before deadline"] = {k: me(ta)[k] for k in ("available", "held")}
time.sleep(4.5)
exp = call("GET", "/_test/export")[1]["state"]["authorizations"]["a_x"]["status"]
out["after deadline (first read is export)"] = (exp, {k: me(ta)[k] for k in ("available", "held")})

if S1:
    call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_ada", "ada", 100), U("u_bob", "bob", 0)]}, base=S1)
    t1 = login("ada", S1)
    call("POST", "/payments", {"to_handle": "bob", "amount": 40}, t1, "up1", base=S1)
    e1 = call("GET", "/_test/export", base=S1)[1]
    out["stage-1 export -> stage-2 import"] = c(call("POST", "/_test/import", e1))
    out["stage-1 token after import"] = {k: me(t1).get(k) for k in ("balance", "total", "available", "held")}
    out["stage-1 replay after import"] = c(call("POST", "/payments", {"to_handle": "bob", "amount": 40}, t1, "up1"))
for k, v in out.items():
    print(k, "->", v)
