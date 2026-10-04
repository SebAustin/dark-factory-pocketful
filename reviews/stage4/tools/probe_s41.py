"""Verifier probe for S4.1 refunds.   python3 reviews/stage4/tools/probe_s41.py http://127.0.0.1:<port>"""
import concurrent.futures as cf
import json
import sys
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

B = sys.argv[1].rstrip("/")
PW = "correct horse"
out = []


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


def c(r):
    return (r[0], (r[1] or {}).get("error", {}).get("code")) if r[0] >= 400 else r[0]


def check(name, cond, detail=""):
    out.append(bool(cond))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": PW, "display_name": h, "handle": h, "balance": b}
K = lambda: uuid.uuid4().hex
ago = lambda s: (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def reset(extra=None):
    fx = {"currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"],
          "users": [U("u_a", "a", 10000), U("u_b", "b", 1000), U("u_c", "c", 1000), U("u_op", "op", 0)]}
    assert call("POST", "/_test/reset", dict(fx, **(extra or {})))[0] == 204
    return {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": PW})[1]["token"] for h in ("a", "b", "c", "op")}


T = reset()
p = call("POST", "/payments", {"to_handle": "b", "amount": 1000, "note": "dinner ☕", "visibility": "private"}, T["a"], K())[1]
key = K()
r = call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 200}, T["b"], key)
rf = r[1]
check("201 opposite payment, refund_of, nulls, note/visibility copied",
      r[0] == 201 and (rf["from_user_id"], rf["to_user_id"], rf["amount"], rf["refund_of"], rf["request_id"], rf["authorization_id"], rf["note"], rf["visibility"])
      == ("u_b", "u_a", 200, p["payment_id"], None, None, "dinner ☕", "private") and set(rf) >= set(p), str(sorted(rf)))
check("other payments carry refund_of null", call("GET", "/activity", t=T["a"])[1]["payments"][-1].get("refund_of", "MISSING") is None)
check("replay 200 identical; different body same key 409", call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 200}, T["b"], key) == (200, rf)
      and c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 201}, T["b"], key)) == (409, "idempotency_key_reuse"))
me = lambda h: call("GET", "/me", t=T[h])[1]
check("balances moved", (me("a")["total"], me("b")["total"]) == (10000 - 1000 + 200, 1000 + 1000 - 200))
check("refund appears in feed and in both statements once",
      sum(x["payment_id"] == rf["payment_id"] for x in call("GET", "/activity", t=T["b"])[1]["payments"]) == 1
      and all(sum(e["payment"]["payment_id"] == rf["payment_id"] for e in call("GET", "/statement?limit=200", t=T[h])[1]["entries"]) == 1 for h in "ab"))
codes = {
    "sender refunds": c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, T["a"], K())),
    "third party": c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, T["c"], K())),
    "unknown": c(call("POST", "/payments/p_nope/refunds", {"amount": 1}, T["b"], K())),
    "amount 0/-1/1.5/'5'/true/missing/1e9+1": [c(call("POST", "/payments/%s/refunds" % p["payment_id"], b, T["b"], K()))
                                              for b in ({"amount": 0}, {"amount": -1}, {"amount": 1.5}, {"amount": "5"}, {"amount": True}, {}, {"amount": 1000000001})],
    "exceeds remaining 801": c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 801}, T["b"], K())),
    "refund of the refund by its receiver": c(call("POST", "/payments/%s/refunds" % rf["payment_id"], {"amount": 1}, T["a"], K())),
    "correct the refund (its sender)": c(call("POST", "/payments/%s/corrections" % rf["payment_id"], {"expected_revision": 1, "amount": 1, "effective_at": ago(1), "reason": "x"}, T["b"], K())),
    "no key": c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, T["b"])),
    "no token": c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, None, K())),
}
print("     codes:", codes)
check("error table", codes["sender refunds"] == (403, "forbidden") and codes["third party"] == (403, "forbidden") and codes["unknown"] == (404, "not_found")
      and all(x == (422, "validation_failed") for x in codes["amount 0/-1/1.5/'5'/true/missing/1e9+1"]) and codes["exceeds remaining 801"] == (422, "refund_exceeds_payment")
      and codes["refund of the refund by its receiver"] == (422, "invalid_refund_target") and codes["correct the refund (its sender)"] == (422, "linked_payment_immutable")
      and codes["no key"] == (400, "missing_idempotency_key") and codes["no token"] == (401, "unauthenticated"))
check("exactly to the cap (800) then 1 more refused", call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 800}, T["b"], K())[0] == 201
      and c(call("POST", "/payments/%s/refunds" % p["payment_id"], {"amount": 1}, T["b"], K())) == (422, "refund_exceeds_payment"))
# cap follows corrections; correction cannot go below refunded
T = reset()
q = call("POST", "/payments", {"to_handle": "b", "amount": 1000}, T["a"], K())[1]
call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 300}, T["b"], K())
corr = lambda amt, rev: c(call("POST", "/payments/%s/corrections" % q["payment_id"], {"expected_revision": rev, "amount": amt, "effective_at": ago(0.5), "reason": "r"}, T["a"], K()))
check("correction below refunded -> 422 refund_exceeds_payment; exactly refunded ok", corr(299, 1) == (422, "refund_exceeds_payment") and corr(300, 1) == 201)
check("cap follows the corrected amount (300 corrected, 300 refunded -> 1 more refused)",
      c(call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 1}, T["b"], K())) == (422, "refund_exceeds_payment"))
# available, not total: holds count
T = reset()
q = call("POST", "/payments", {"to_handle": "b", "amount": 500}, T["a"], K())[1]
call("POST", "/authorizations", {"to_handle": "c", "amount": 1400}, T["b"], K())            # b: total 1500, held 1400, available 100
check("refund checked against available (101 vs 100)", c(call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 101}, T["b"], K())) == (409, "insufficient_funds")
      and call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 100}, T["b"], K())[0] == 201)
# request, capture, settlement targets
T = reset()
rq = call("POST", "/requests", {"payer_handle": "a", "amount": 300}, T["b"], K())[1]
pay = call("POST", "/requests/%s/pay" % rq["request_id"], {}, T["a"], K())[1]
s1 = call("POST", "/payments/%s/refunds" % pay["payment_id"], {"amount": 300}, T["b"], K())
st = call("GET", "/requests", t=T["b"])[1]["requests"][0]["status"]
au = call("POST", "/authorizations", {"to_handle": "b", "amount": 400}, T["a"], K())[1]
cap = call("POST", "/authorizations/%s/capture" % au["authorization_id"], {"amount": 150}, T["b"], K())[1]
s2 = call("POST", "/payments/%s/refunds" % cap["payment_id"], {"amount": 150}, T["b"], K())
a_ = [x for x in call("GET", "/authorizations", t=T["a"])[1]["authorizations"] if x["authorization_id"] == au["authorization_id"]][0]
sett = call("POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "c", "amount": 70}]}, T["op"], K())[1]
s3 = call("POST", "/payments/%s/refunds" % sett["payments"][0]["payment_id"], {"amount": 70}, T["c"], K())
replay = call("POST", "/settlements", {"transfers": [{"from_handle": "a", "to_handle": "c", "amount": 70}]}, T["op"], None)
check("request payment refund: 201, request stays paid", s1[0] == 201 and st == "paid")
check("capture refund: 201, authorization unchanged (captured, held 0)", s2[0] == 201 and a_["status"] == "captured" and me("a")["held"] == 0)
check("settlement member refund: 201, refund has settlement_id null, member keeps its settlement",
      s3[0] == 201 and s3[1]["settlement_id"] is None and s3[1]["refund_of"] == sett["payments"][0]["payment_id"])
# concurrency
T = reset()
q = call("POST", "/payments", {"to_handle": "b", "amount": 1000}, T["a"], K())[1]
with cf.ThreadPoolExecutor(20) as ex:
    res = list(ex.map(lambda i: c(call("POST", "/payments/%s/refunds" % q["payment_id"], {"amount": 300}, T["b"], K())), range(20)))
check("20 concurrent 300-refunds on 1000 -> exactly 3 x 201", Counter(map(str, res))["201"] == 3, str(Counter(map(str, res))))
tot = sum(call("GET", "/me", t=t)[1]["total"] for t in T.values())
check("sum of totals constant", tot == 12000, tot)
pts = sorted({e["effective_at"] for e in call("GET", "/statement?limit=200", t=T["b"])[1]["entries"]})
check("sum constant in as_of views at every entry instant", all(sum(call("GET", "/me?as_of=%s" % urllib.parse.quote(t_, safe=""), t=t)[1]["total"] for t in T.values()) == 12000 for t_ in pts))
print("PASS" if all(out) else "FAIL")
