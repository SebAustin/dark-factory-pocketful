import json, sys, threading, urllib.request, concurrent.futures as cf
from collections import Counter

B = sys.argv[1]


def call(method, path, body=None, tok=None, key=None, raw=None):
    h = {"Content-Type": "application/json"}
    if tok: h["Authorization"] = "Bearer " + tok
    if key is not None: h["Idempotency-Key"] = key
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    r = urllib.request.Request(B + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=5) as x:
            t = x.read(); return x.status, json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def code(r): return (r[0], r[1]["error"]["code"]) if r[0] >= 400 else r[0]


U = lambda i, h, bal: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": bal}
F = {"currency": "EUR", "minor_units": 2, "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 2500), U("u_cy", "cy", 0)],
     "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                  {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "secret", "visibility": "private"}]}
assert call("POST", "/_test/reset", F)[0] == 204
tok = {h: call("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"] for h in ("ada", "bob", "cy")}
A = tok["ada"]
P = lambda body, key="k", t="ADA", raw=None: call("POST", "/payments", body, tok["ada"] if t == "ADA" else t, key, raw)
bal = lambda h: call("GET", "/me", tok=tok[h])[1]["balance"]
out = {}
out["no key"] = code(P({"to_handle": "bob", "amount": 1}, key=None))
out["empty key"] = code(P({"to_handle": "bob", "amount": 1}, key=""))
out["key 256"] = code(P({"to_handle": "bob", "amount": 1}, key="x" * 256))
out["key 255 first"] = code(P({"to_handle": "bob", "amount": 1}, key="x" * 255))
r1 = P({"to_handle": "bob", "amount": 1000, "note": "dinner 🍕   <b>&", "visibility": "private"}, key="k1")
out["first"] = r1[0]
out["note verbatim"] = r1[1]["note"] == "dinner 🍕   <b>&"
out["keys"] = sorted(r1[1])
r2 = P(None, key="k1", raw=b'{ "visibility":"private","note":"dinner \xf0\x9f\x8d\x95 \xc2\xa0 <b>&",  "amount": 1e3, "to_handle":"bob"}')
out["replay reordered 1e3"] = (r2[0], r2[1] == r1[1])
out["replay 1000.0"] = P(None, key="k1", raw='{"to_handle":"bob","amount":1000.0,"note":"dinner 🍕   <b>&","visibility":"private"}'.encode())[0]
out["diff body"] = code(P({"to_handle": "bob", "amount": 1001}, key="k1"))
out["invalid body same key"] = code(P({"to_handle": "ada", "amount": -5}, key="k1"))
out["bal after 1 effect"] = (bal("ada"), bal("bob"))
out["other user same key"] = code(P({"to_handle": "ada", "amount": 1}, key="k1", t=tok["bob"]))
out["key after 4xx"] = [code(P({"to_handle": "bob", "amount": 99999999}, key="k2")), code(P({"to_handle": "bob", "amount": 5}, key="k2"))]
out["path differs"] = code(call("POST", "/payments?x=1", {"to_handle": "bob", "amount": 5}, A, "k2"))
out["bool amount"] = code(P({"to_handle": "bob", "amount": True}, key="b1"))
out["str amount"] = code(P({"to_handle": "bob", "amount": "5"}, key="b2"))
out["1.5 amount"] = code(P({"to_handle": "bob", "amount": 1.5}, key="b3"))
out["0 / 1e9+1 / 1e9"] = [code(P({"to_handle": "bob", "amount": a}, key="b4" + str(a))) for a in (0, 1000000001)] + [code(P({"to_handle": "cy", "amount": 1000000000}, key="b5"))]
out["self"] = code(P({"to_handle": "ada", "amount": 1}, key="b6"))
out["unknown"] = code(P({"to_handle": "zzz", "amount": 1}, key="b7"))
out["note 201"] = code(P({"to_handle": "bob", "amount": 1, "note": "x" * 201}, key="b8"))
out["note null"] = code(P({"to_handle": "bob", "amount": 1, "note": None}, key="b9"))
out["vis bad"] = code(P({"to_handle": "bob", "amount": 1, "visibility": "friends"}, key="b10"))
out["handle int"] = code(P({"to_handle": 5, "amount": 1}, key="b11"))
out["missing to"] = code(P({"amount": 1}, key="b12"))
out["unauth"] = code(P({"to_handle": "bob", "amount": 1}, t=None))
out["insufficient"] = code(P({"to_handle": "ada", "amount": 1}, key="c1", t=tok["cy"]))
out["insufficient then funded"] = None
# feed
feed = lambda h, q="": call("GET", "/activity" + q, tok=tok[h])
f_cy = [p["note"] for p in feed("cy")[1]["payments"]]
f_bob = [p["note"] for p in feed("bob")[1]["payments"]]
out["cy sees private?"] = ("secret" in f_cy, any("dinner" in n for n in f_cy))
out["bob sees private"] = ("secret" in f_bob, any("dinner" in n for n in f_bob))
out["order bob"] = f_bob[:3]
out["paging"] = [(lambda r: (len(r[1]["payments"]), r[1]["has_more"]))(feed("bob", "?limit=1&offset=0")), code(feed("bob", "?limit=0")), code(feed("bob", "?limit=201")), code(feed("bob", "?limit=1e1")), code(feed("bob", "?offset=-1")), code(feed("bob", "?limit=+4")), feed("bob", "?limit=200&foo=bar")[0]]
# concurrency: same key 50 threads, 3 runs
for run in range(3):
    call("POST", "/_test/reset", F)
    A = tok["ada"] = call("POST", "/auth/login", {"email": "ada@e.com", "password": "correct horse"})[1]["token"]
    tok["bob"] = call("POST", "/auth/login", {"email": "bob@e.com", "password": "correct horse"})[1]["token"]
    tok["cy"] = call("POST", "/auth/login", {"email": "cy@e.com", "password": "correct horse"})[1]["token"]
    with cf.ThreadPoolExecutor(50) as ex:
        res = list(ex.map(lambda i: P({"to_handle": "bob", "amount": 700}, key="same"), range(50)))
    bodies = {json.dumps(b, sort_keys=True) for s, b in res}
    with cf.ThreadPoolExecutor(50) as ex:
        dr = list(ex.map(lambda i: P({"to_handle": "cy" if i % 2 else "ada", "amount": 1000}, key="d%d" % i, t=A if i % 2 else tok["bob"]), range(50)))
    with cf.ThreadPoolExecutor(50) as ex:
        dr2 = list(ex.map(lambda i: P({"to_handle": "ada", "amount": 300}, key="e%d" % i, t=tok["cy"]), range(50)))
    bs = [bal(h) for h in ("ada", "bob", "cy")]
    print("run", run, "same-key", Counter(s for s, _ in res), "bodies", len(bodies),
          "| drain", Counter(code(r) if r[0] >= 400 else r[0] for r in dr + dr2), "| balances", bs, "sum", sum(bs), "min", min(bs))
for k, v in out.items(): print(k, "->", v)
