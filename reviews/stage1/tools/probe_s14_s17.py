"""Verifier black-box probes for S1.4 requests, S1.5 splits, S1.6 settlements, S1.7 export/import."""
import json, sys, urllib.request, concurrent.futures as cf
from collections import Counter

B = sys.argv[1]


def call(method, path, body=None, tok=None, key=None, raw=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key is not None: h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(B + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as x:
            t = x.read(); return x.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        t = e.read(); return e.code, json.loads(t) if t else None


def c(r): return (r[0], r[1]["error"]["code"]) if r[0] >= 400 else r[0]


U = lambda i, h, bal: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": bal}
F = {"currency": "EUR", "minor_units": 2,
     "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 2500), U("u_cy", "cy", 0), U("u_op", "op", 0)],
     "settlement_operator_ids": ["u_op"]}
tok = {}


def reset(f=F):
    assert call("POST", "/_test/reset", f)[0] == 204
    for u in f["users"]:
        tok[u["handle"]] = call("POST", "/auth/login", {"email": u["email"], "password": "correct horse"})[1]["token"]


bal = lambda h: call("GET", "/me", tok=tok[h])[1]["balance"]
out = {}

# ---------------- S1.4 requests
reset()
R = lambda body, key, who="bob": call("POST", "/requests", body, tok[who], key)
r = R({"payer_handle": "ada", "amount": 50000, "note": "big"}, "r1")
out["4 create > balance"] = (r[0], r[1]["status"], sorted(r[1]))
rid = r[1]["request_id"]
out["4 errors"] = [c(R({"payer_handle": "ada", "amount": a}, "e%s" % a)) for a in (0, 1000000001, 1.5, "5", True)] + \
    [c(R({"payer_handle": "bob", "amount": 1}, "e6")), c(R({"payer_handle": "ada", "amount": 1, "note": "x" * 201}, "e7")),
     c(R({"payer_handle": "zz", "amount": 1}, "e8")), c(R({"payer_handle": "ada", "amount": 1}, None))]
pay = lambda rid, body, key, who="ada": call("POST", "/requests/%s/pay" % rid, body, tok[who], key)
out["4 pay short"] = c(pay(rid, {}, "p1"))
out["4 pay not payer / third / unknown"] = [c(pay(rid, {}, "p2", "bob")), c(pay(rid, {}, "p3", "cy")), c(pay("rq_nope", {}, "p4"))]
call("POST", "/payments", {"to_handle": "ada", "amount": 2500}, tok["bob"], "fund")
call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "ada", "amount": 0}]}, tok["op"], "x")
# fund ada to 60000 via op? op has 0; just pay a smaller request instead
r2 = R({"payer_handle": "ada", "amount": 1200, "note": "taxi"}, "r2")[1]
p = pay(r2["request_id"], {"visibility": "private"}, "k")
out["4 pay"] = (p[0], p[1]["request_id"] == r2["request_id"], p[1]["visibility"], p[1]["amount"])
out["4 replay paid"] = (lambda x: (x[0], x[1] == p[1]))(pay(r2["request_id"], {"visibility": "private"}, "k"))
out["4 {} vs public"] = c(pay(r2["request_id"], {}, "k"))
out["4 new key paid"] = c(pay(r2["request_id"], {}, "k2"))
out["4 decline paid / cancel paid"] = [c(call("POST", "/requests/%s/decline" % r2["request_id"], {}, tok["ada"])), c(call("POST", "/requests/%s/cancel" % r2["request_id"], None, tok["bob"]))]
r3 = R({"payer_handle": "ada", "amount": 1}, "r3")[1]["request_id"]
out["4 decline twice / cancel declined / not payer"] = [c(call("POST", "/requests/%s/decline" % r3, None, tok["bob"])), c(call("POST", "/requests/%s/decline" % r3, None, tok["ada"])), c(call("POST", "/requests/%s/decline" % r3, None, tok["ada"])), c(call("POST", "/requests/%s/cancel" % r3, None, tok["bob"])), c(pay(r3, {}, "p9"))]
r4 = R({"payer_handle": "ada", "amount": 1}, "r4")[1]["request_id"]
out["4 cancel twice / decline cancelled"] = [c(call("POST", "/requests/%s/cancel" % r4, None, tok["bob"])), c(call("POST", "/requests/%s/cancel" % r4, None, tok["bob"])), c(call("POST", "/requests/%s/decline" % r4, None, tok["ada"]))]
L = lambda who, q="": call("GET", "/requests" + q, tok=tok[who])
out["4 list cy"] = len(L("cy")[1]["requests"])
out["4 list ada incoming pending"] = [x["request_id"] for x in L("ada", "?direction=incoming&status=pending")[1]["requests"]]
out["4 list bob outgoing count / order newest first"] = (len(L("bob", "?direction=outgoing")[1]["requests"]), [x["request_id"] for x in L("bob")[1]["requests"]])
out["4 list bad"] = [c(L("bob", q)) for q in ("?direction=x", "?status=open", "?limit=0", "?offset=-1", "?limit=1e1")] + [(lambda x: (len(x[1]["requests"]), x[1]["has_more"]))(L("bob", "?limit=1"))]
out["4 feed: requests absent"] = all("request_id" in x for x in call("GET", "/activity", tok=tok["cy"])[1]["payments"])
# concurrent pay race 3 runs
for run in range(3):
    reset()
    rr = R({"payer_handle": "ada", "amount": 300}, "race")[1]["request_id"]
    with cf.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: c(pay(rr, {}, "k%d" % (i % 25))), range(50)))
    out["4 race run%d" % run] = (Counter(map(str, res)), bal("ada"), bal("bob"))
# ---------------- S1.5 splits
reset()
S = lambda body, key, who="ada": call("POST", "/splits", body, tok[who], key)
s = S({"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"}, "s1")
out["5 example"] = (s[0], s[1]["shares"], [(x["payer_handle"], x["amount"], x["requester_handle"]) for x in s[1]["requests"]], sorted(s[1]))
out["5 table"] = [[x["amount"] for x in S({"amount": a, "participant_handles": ["bob", "cy", "op", "ada", "x"][:n] if n <= 4 else ["bob", "cy", "op", "ada", "bob2"][:n]}, "t%d%d" % (a, n))[1].get("shares", [{"amount": "ERR"}])] for a, n in ((1000, 3), (1, 3), (10, 3), (999, 3))]
out["5 order moves unit"] = [x["amount"] for x in S({"amount": 10, "participant_handles": ["cy", "bob", "op"]}, "o1")[1]["shares"]]
out["5 caller only"] = (lambda x: (x[0], x[1]["requests"], x[1]["shares"]))(S({"amount": 7, "participant_handles": ["ada"]}, "only"))
z = S({"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, "zero")
out["5 zero share request"] = [(x["payer_handle"], x["amount"], x["status"]) for x in z[1]["requests"]]
out["5 errors"] = [c(S({"amount": a, "participant_handles": ["bob"]}, "se%s" % a)) for a in (0, 1000000001, 2.5, "3")] + \
    [c(S({"amount": 5, "participant_handles": h}, "sh%d" % i)) for i, h in enumerate(([], ["bob", "bob"], ["bob", "zzz"], ["BOB"], "bob", [1]))] + \
    [c(S({"amount": 5, "participant_handles": ["bob"], "note": "x" * 201}, "sn"))]
out["5 replay"] = (lambda x: (x[0], x[1] == s[1]))(S({"note": "dinner", "participant_handles": ["ada", "bob", "cy"], "amount": 3000.0}, "s1"))
out["5 replay reorder handles"] = c(S({"amount": 3000, "participant_handles": ["bob", "ada", "cy"], "note": "dinner"}, "s1"))
# ---------------- S1.6 settlements
reset()
ST = lambda body, key, who="op": call("POST", "/settlements", body, tok[who], key)
t = lambda f, to, a, **k: dict(from_handle=f, to_handle=to, amount=a, **k)
out["6 auth"] = [c(call("POST", "/settlements", {"transfers": [t("ada", "bob", 1)]}, None, "a")), c(ST({"transfers": [t("ada", "bob", 1)]}, "a", "ada")), c(ST({"transfers": [t("ada", "bob", 1)]}, None))]
# net-affordable chain: cy has 0, receives 5000 from ada and sends 5000 to bob
g = ST({"transfers": [t("cy", "bob", 5000, note="n2", visibility="private"), t("ada", "cy", 5000)], "extra": 1}, "g1")
out["6 net chain"] = (g[0], [(x["from_handle"], x["to_handle"], x["settlement_id"] == g[1]["settlement_id"], x["created_at"] == g[1]["committed_at"], x["request_id"]) for x in g[1]["payments"]], sorted(g[1]))
out["6 balances"] = [bal(h) for h in ("ada", "bob", "cy", "op")]
out["6 unaffordable"] = (c(ST({"transfers": [t("cy", "bob", 1), t("ada", "bob", 1)]}, "u1")), [bal(h) for h in ("ada", "bob", "cy")])
out["6 precedence"] = [c(ST({"transfers": [t("zz", "bob", 1), t("ada", "ada", 1)]}, "pr1")), c(ST({"transfers": [t("ada", "ada", 1), t("zz", "bob", 1)]}, "pr2")),
                       c(ST({"transfers": [t("cy", "bob", 99999), t("ada", "zz", 1)]}, "pr3")), c(ST({"transfers": [t("ada", "bob", 0)]}, "pr4"))]
out["6 shape"] = [c(ST(b, "sh%d" % i)) for i, b in enumerate(({}, {"transfers": []}, {"transfers": [t("ada", "bob", 1)] * 33}, {"transfers": [5]}, {"transfers": "x"}, {"transfers": [{"from_handle": 1, "to_handle": "bob", "amount": 1}]}))]
out["6 32 ok"] = c(ST({"transfers": [t("ada", "bob", 1)] * 32}, "ok32"))
out["6 replay"] = (lambda x: (x[0], x[1] == g[1]))(ST({"transfers": [t("cy", "bob", 5000, note="n2", visibility="private"), t("ada", "cy", 5000)], "extra": 1}, "g1"))
out["6 failed key reusable"] = c(ST({"transfers": [t("ada", "bob", 1)]}, "u1"))
out["6 nonmember settlement_id null"] = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, tok["ada"], "pp")[1]["settlement_id"]
feed_op = call("GET", "/activity", tok=tok["op"])[1]["payments"]
out["6 op no private / no requests"] = (any(x["visibility"] == "private" for x in feed_op), call("GET", "/requests", tok=tok["op"])[1]["requests"])
# ---------------- S1.7 export/import
reset()
call("POST", "/payments", {"to_handle": "bob", "amount": 100}, tok["ada"], "x1")
S({"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, "zero")   # creates 0-amount requests
ST({"transfers": [t("ada", "cy", 10)]}, "st1")
call("POST", "/payments", {"to_handle": "bob", "amount": 99999999}, tok["ada"], "failed")
exp = call("GET", "/_test/export")
out["7 export"] = (exp[0], exp[1]["track"], exp[1]["format_version"])
reset({"currency": "JPY", "minor_units": 0, "users": [U("u_z", "zed", 5)]})
imp = call("POST", "/_test/import", exp[1])
out["7 import unchanged export with zero-share split"] = c(imp) if imp[0] != 204 else 204
# without the zero-share split
reset()
old_ada = tok["ada"]
p1 = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, tok["ada"], "x1")
call("POST", "/payments", {"to_handle": "bob", "amount": 99999999}, tok["ada"], "failed")
s1 = ST({"transfers": [t("ada", "cy", 10)]}, "st1")
exp = call("GET", "/_test/export")[1]
call("POST", "/payments", {"to_handle": "bob", "amount": 7}, old_ada, "after")
reset({"currency": "JPY", "minor_units": 0, "users": [U("u_z", "zed", 5)]})
out["7 import"] = c(call("POST", "/_test/import", exp))
out["7 import twice"] = c(call("POST", "/_test/import", exp))
out["7 old token / balances"] = (call("GET", "/me", tok=old_ada)[1], )
out["7 replays"] = [(lambda x: (x[0], x[1] == p1[1]))(call("POST", "/payments", {"to_handle": "bob", "amount": 100}, old_ada, "x1")),
                    (lambda x: (x[0], x[1] == s1[1]))(ST({"transfers": [t("ada", "cy", 10)]}, "st1"))]
out["7 failed key reusable / zed gone"] = (c(call("POST", "/payments", {"to_handle": "bob", "amount": 1}, old_ada, "failed")), c(call("POST", "/auth/login", {"email": "zed@e.com", "password": "correct horse"})))
out["7 login"] = c(call("POST", "/auth/login", {"email": "ada@e.com", "password": "correct horse"}))
out["7 invalid"] = [c(call("POST", "/_test/import", b)) for b in ({}, {"track": "x", "format_version": 1, "state": exp["state"]}, {"track": "pocketful", "format_version": 2, "state": exp["state"]}, {"track": "pocketful", "format_version": 1}, {"track": "pocketful", "format_version": 1, "state": {"users": 1}})] + [c(call("POST", "/_test/import", raw=b"{bad"))]
out["7 state intact after invalid"] = bal("ada") if False else call("GET", "/me", tok=old_ada)[1]["balance"]
reset()
out["7 reset clears import"] = c(call("GET", "/me", tok=old_ada))
for k, v in out.items(): print(k, "->", v)
