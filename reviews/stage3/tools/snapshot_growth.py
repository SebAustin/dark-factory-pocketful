"""Repro for S3.3 F1/F2: statement snapshots grow memory and the export without bound.

    python3 reviews/stage3/tools/snapshot_growth.py http://127.0.0.1:<port> [reads=5500]
Seeds a wallet with 500 payments, performs N first-page statement reads (limit=1), then exports and re-imports the unchanged export.
"""
import concurrent.futures as cf
import json
import sys
import urllib.request

B = sys.argv[1].rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5500


def call(m, p, b=None, t=None, k=None, raw=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = "Bearer " + t
    if k:
        h["Idempotency-Key"] = k
    r = urllib.request.Request(B + p, data=raw if raw is not None else (None if b is None else json.dumps(b).encode()), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=120) as x:
            return x.status, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError as e:
        return "connection error", repr(e).encode()


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_a", "a", 10 ** 9), U("u_b", "b", 0)]})
t = json.loads(call("POST", "/auth/login", {"email": "a@e.com", "password": "correct horse"})[1])["token"]
for i in range(500):
    call("POST", "/payments", {"to_handle": "b", "amount": 1}, t, "k%d" % i)
with cf.ThreadPoolExecutor(20) as ex:
    list(ex.map(lambda i: call("GET", "/statement?limit=1", t=t), range(N)))
s, d = call("GET", "/_test/export")
print("export", s, "size MB", round(len(d) / 1e6, 1))
s, r = call("POST", "/_test/import", raw=d)
print("import of the unchanged export ->", s, r[:120])
