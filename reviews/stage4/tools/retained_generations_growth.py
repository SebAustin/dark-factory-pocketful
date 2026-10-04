"""Repro for S4.3 F10: each import retains one generation per outgoing state that a live snapshot points at; the export and the
memory grow as (imports with a live snapshot) x (state size), and the service then refuses its own unchanged export.

    python3 reviews/stage4/tools/retained_generations_growth.py http://127.0.0.1:<port> [payments=20000] [cycles=30] [container] [--drift] [--correct]
Seeds one sender with `payments` payments, exports that state E, then `cycles` times: read one statement page (a live snapshot),
import E without a reset (tokens survive per L12). Every snapshot must still page identically. Finally the service is exported and
that unchanged export is re-imported.
"""
import concurrent.futures as cf
import json
import subprocess
import sys
import time
import urllib.request

B = sys.argv[1].rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
CYCLES = int(sys.argv[3]) if len(sys.argv) > 3 else 30
CONTAINER = sys.argv[4] if len(sys.argv) > 4 else None
DRIFT = "--drift" in sys.argv          # one extra payment before each read, so every replaced state differs
CORRECT = "--correct" in sys.argv      # a correction of an early payment before each read: a change inside the history


def call(m, p, b=None, t=None, k=None, raw=None):
    h = {"Content-Type": "application/json"}
    if t:
        h["Authorization"] = "Bearer " + t
    if k:
        h["Idempotency-Key"] = k
    r = urllib.request.Request(B + p, data=raw if raw is not None else (None if b is None else json.dumps(b).encode()), method=m, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=600) as x:
            return x.status, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except OSError as e:
        return "connection error", repr(e).encode()


def mem():
    if not CONTAINER:
        return "n/a"
    return subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", CONTAINER], capture_output=True, text=True).stdout.strip()


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h, "handle": h, "balance": b}
call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [U("u_a", "a", 10 ** 9), U("u_b", "b", 0)]})
t = json.loads(call("POST", "/auth/login", {"email": "a@e.com", "password": "correct horse"})[1])["token"]
with cf.ThreadPoolExecutor(16) as ex:
    seeded = list(ex.map(lambda i: call("POST", "/payments", {"to_handle": "b", "amount": 1}, t, "s%d" % i), range(N)))
PIDS = [json.loads(b)["payment_id"] for _, b in seeded]
_, E = call("GET", "/_test/export")
print("seeded %d payments: export %.1f MB, memory %s" % (N, len(E) / 1e6, mem()))
snaps = []
for i in range(CYCLES):
    if DRIFT:
        call("POST", "/payments", {"to_handle": "b", "amount": 1}, t, "d%d" % i)
    if CORRECT:
        pid = PIDS[(i * 7919) % N]
        eff = json.loads(call("GET", "/payments/%s/revisions" % pid, t=t)[1])["revisions"][0]["effective_at"]
        assert call("POST", "/payments/%s/corrections" % pid, {"expected_revision": 1, "amount": 2, "effective_at": eff, "reason": "drift"}, t, "c%d" % i)[0] == 201
    s, st = call("GET", "/statement?limit=2", t=t)
    snap = json.loads(st)["snapshot"]
    snaps.append((snap, call("GET", "/statement?snapshot=%s&limit=2&offset=%d" % (snap, N - 2), t=t)))
    assert call("POST", "/_test/import", raw=E)[0] == 204
print("after %d imports, each with a live snapshot: memory %s" % (CYCLES, mem()))
same = all(call("GET", "/statement?snapshot=%s&limit=2&offset=%d" % (sn, N - 2), t=t) == page for sn, page in snaps)
print("all %d snapshots page identically: %s" % (CYCLES, same))
t0 = time.time()
s, X = call("GET", "/_test/export")
print("export: %s, %.1f MB in %.1f s (64 MiB import cap = 67.1 MB)" % (s, len(X) / 1e6, time.time() - t0))
t0 = time.time()
r = call("POST", "/_test/import", raw=X)
print("re-import of the unchanged export: %s in %.1f s %s" % (r[0], time.time() - t0, r[1][:160]))
