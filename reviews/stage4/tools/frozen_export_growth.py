"""Repro for S4.3 F9: snapshots bound to a replaced state are exported fully rendered; the export grows as reads x window.

    python3 reviews/stage4/tools/frozen_export_growth.py http://127.0.0.1:<port> [reads=1000]
State B is exported. State A gets 300 payments, then N rounds of (one payment, one first-page statement read), giving N distinct windows.
B is imported without a reset (A's tokens survive per L12), then the service is exported and that unchanged export is re-imported.
"""
import json
import sys
import time
import urllib.request

B = sys.argv[1].rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1000


def call(m, p, b=None, t=None, k=None, raw=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = "Bearer " + t
    if k:
        h["Idempotency-Key"] = k
    r = urllib.request.Request(B + p, data=raw if raw is not None else (None if b is None else json.dumps(b).encode()), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=300) as x:
            return x.status, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError as e:
        return "connection error", repr(e).encode()


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_z", "z", 5)]})
_, EB = call("GET", "/_test/export")
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_a", "a", 10 ** 9), U("u_b", "b", 0)]})
t = json.loads(call("POST", "/auth/login", {"email": "a@e.com", "password": "correct horse"})[1])["token"]
for i in range(300):
    call("POST", "/payments", {"to_handle": "b", "amount": 1}, t, "s%d" % i)
for i in range(N):
    call("POST", "/payments", {"to_handle": "b", "amount": 1}, t, "p%d" % i)
    call("GET", "/statement?limit=1", t=t)
print("import B without reset:", call("POST", "/_test/import", raw=EB)[0])
t0 = time.time()
s, e = call("GET", "/_test/export")
print("export:", s, round(len(e) / 1e6, 1), "MB in %.1f s" % (time.time() - t0))
r = call("POST", "/_test/import", raw=e)
print("re-import of the unchanged export:", r[0], r[1][:120])
