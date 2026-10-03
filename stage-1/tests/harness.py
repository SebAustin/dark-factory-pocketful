"""In-process test harness: starts the service on an ephemeral port."""
import http.client
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import server  # noqa: E402

_SERVER = None
_PORT = None
_LOCK = threading.Lock()


def port():
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is None:
            _SERVER = server.make_server("127.0.0.1", 0)
            _PORT = _SERVER.server_address[1]
            threading.Thread(target=_SERVER.serve_forever, daemon=True).start()
        return _PORT


class Resp:
    def __init__(self, status, raw, headers):
        self.status = status
        self.raw = raw
        self.headers = headers
        self.body = json.loads(raw) if raw else None

    @property
    def code(self):
        return (self.body or {}).get("error", {}).get("code")


def call(method, path, body=None, token=None, key=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port(), timeout=10)
    hdrs = {"Content-Type": "application/json"}
    if token is not None:
        hdrs["Authorization"] = "Bearer " + token
    if key is not None:
        hdrs["Idempotency-Key"] = key
    hdrs.update(headers or {})
    data = raw if raw is not None else (None if body is None else json.dumps(body))
    if isinstance(data, str):
        data = data.encode("utf-8")
    conn.request(method, path, body=data, headers=hdrs)
    r = conn.getresponse()
    out = Resp(r.status, r.read().decode("utf-8"), dict(r.getheaders()))
    conn.close()
    return out


FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
    ],
    "payments": [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 500, "note": "coffee", "visibility": "public"},
    ],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 1200, "note": "taxi", "status": "pending"},
    ],
}


def reset(fixture=None):
    r = call("POST", "/_test/reset", fixture if fixture is not None else FIXTURE)
    assert r.status == 204, (r.status, r.raw)
