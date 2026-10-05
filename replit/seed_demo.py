"""Seed the Replit demo (deployment glue, not part of the band's output).

Loads the band's own acceptance fixture (ada, bob, cy, dee and an operator) through the
service's internal port, then adds a little history through the public API: a payment, a
refund, an open hold and a pending request, so every screen has something to show.
Every demo user's password is "correct horse". Python standard library only.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

APP = f"http://127.0.0.1:{int(os.environ.get('APP_PORT') or 18080)}"
PASSWORD = "correct horse"
USERS = [("u_ada", "ada", "Ada Lovelace", 10000), ("u_bob", "bob", "Bob", 2500), ("u_cy", "cy", "Cy", 0),
         ("u_dee", "dee", "Dee", 5000), ("u_op", "op", "Op", 0)]


def call(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Idempotency-Key"] = "seed-" + uuid.uuid4().hex
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(APP + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def wait_for_health(seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            call("GET", "/health")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit("seed: service did not become healthy")


def main():
    wait_for_health()
    fixture = {"currency": "EUR", "minor_units": 2, "payments": [], "requests": [], "authorizations": [],
               "settlement_operator_ids": ["u_op"],
               "users": [{"id": uid, "email": f"{h}@example.com", "password": PASSWORD, "display_name": name,
                          "handle": h, "balance": bal} for uid, h, name, bal in USERS]}
    call("POST", "/_test/reset", fixture)
    tok = {h: call("POST", "/auth/login", {"email": f"{h}@example.com", "password": PASSWORD})["token"]
           for h in ("ada", "bob")}
    dinner = call("POST", "/payments", {"to_handle": "bob", "amount": 2500, "note": "Dinner at the lake",
                                         "visibility": "public"}, tok["ada"])
    call("POST", f"/payments/{dinner['payment_id']}/refunds", {"amount": 500}, tok["bob"])
    call("POST", "/authorizations", {"to_handle": "ada", "amount": 1500, "note": "Cabin deposit"}, tok["bob"])
    call("POST", "/requests", {"payer_handle": "ada", "amount": 800, "note": "Concert tickets"}, tok["bob"])
    print("seed: demo data loaded (sign in as ada@example.com / correct horse)", flush=True)


if __name__ == "__main__":
    main()
