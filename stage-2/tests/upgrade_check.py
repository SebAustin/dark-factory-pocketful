#!/usr/bin/env python3
"""S2.5: a real stage-1 export imported into stage 2 (stdlib; not in unittest discovery).

    STAGE1_URL=http://127.0.0.1:18220 STAGE2_URL=http://127.0.0.1:18210 \
        python3 stage-2/tests/upgrade_check.py [--save stage-2/tests/fixtures/stage1_export.json]

Drives the frozen stage-1 service through every kind of write, exports it, imports the export
into stage 2 and checks the "Existing clients after an upgrade" rules: signed-in tokens still
work, pending requests stay payable, a payment whose response was "lost" replays with its
original body, balances and held/available are right, and stage 2 export -> import -> export
is stable. Exit 0 = pass.
"""
import http.client
import json
import os
import sys
from urllib.parse import urlsplit

PW = "correct horse"
FIXTURE = {
    "currency": "EUR", "minor_units": 2,
    "users": [{"id": "u_ada", "email": "ada@example.com", "password": PW,
               "display_name": "Ada", "handle": "ada", "balance": 10000},
              {"id": "u_bob", "email": "bob@example.com", "password": PW,
               "display_name": "Bob", "handle": "bob", "balance": 2500},
              {"id": "u_cy", "email": "cy@example.com", "password": PW,
               "display_name": "Cy", "handle": "cy", "balance": 0}],
    "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                  "note": "coffee", "visibility": "public"}],
    "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                  "note": "taxi", "status": "pending"}],
    "settlement_operator_ids": ["u_cy"],
}
failures = []


def call(base, method, path, body=None, token=None, key=None):
    u = urlsplit(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    conn.request(method, path, None if body is None else json.dumps(body), headers)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r.status, (json.loads(raw) if raw else None)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def login(base, email):
    return call(base, "POST", "/auth/login", {"email": email, "password": PW})[1]["token"]


def drive_stage1(s1):
    assert call(s1, "POST", "/_test/reset", FIXTURE)[0] == 204
    ada, bob, cy = (login(s1, e + "@example.com") for e in ("ada", "bob", "cy"))
    status, signup = call(s1, "POST", "/auth/signup", {"email": "dee@example.com",
                                                       "password": PW, "display_name": "Dee"})
    lost = {"to_handle": "bob", "amount": 700, "note": "lost response", "visibility": "private"}
    status, lost_receipt = call(s1, "POST", "/payments", lost, ada, "lost-key")
    check(status == 201, "stage 1: the 'lost' payment commits")
    call(s1, "POST", "/requests", {"payer_handle": "ada", "amount": 300, "note": "lunch"},
         bob, "req-key")
    call(s1, "POST", "/splits", {"amount": 900, "participant_handles": ["ada", "bob", "cy"],
                                 "note": "dinner"}, ada, "split-key")
    call(s1, "POST", "/settlements", {"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 100}]}, cy, "settle-key")
    status, export = call(s1, "GET", "/_test/export")
    check(status == 200 and export.get("format_version") == 1, "stage 1: export 200 v1")
    return export, {"ada": ada, "bob": bob, "cy": cy, "dee": signup["token"]}, lost, lost_receipt


def check_stage2(s2, export, tokens, lost, lost_receipt):
    status, _ = call(s2, "POST", "/_test/import", export)
    check(status == 204, "stage 2: import of the stage-1 export -> 204")
    for name, tok in tokens.items():
        status, me = call(s2, "GET", "/me", token=tok)
        check(status == 200 and me["held"] == 0 and me["available"] == me["total"] == me[
            "balance"], "signed-in token of %s still works; held 0, available = total" % name)
    status, again = call(s2, "POST", "/payments", lost, tokens["ada"], "lost-key")
    check(status == 200 and again == lost_receipt,
          "lost payment replays 200 with the original stage-1 body (D11)")
    status, _ = call(s2, "POST", "/payments", dict(lost, amount=701), tokens["ada"], "lost-key")
    check(status == 409, "same key, different body -> 409 after the upgrade")
    status, listed = call(s2, "GET", "/requests?direction=incoming&status=pending",
                          token=tokens["ada"])
    pending = [r["request_id"] for r in listed["requests"]]
    check(len(pending) >= 2, "pending requests survive (%d)" % len(pending))
    for rid in pending:
        status, paid = call(s2, "POST", "/requests/%s/pay" % rid, {}, tokens["ada"],
                            "pay-" + rid)
        check(status == 201 and paid["authorization_id"] is None,
              "pending request %s payable after the upgrade" % rid)
    totals = sum(call(s2, "GET", "/me", token=t)[1]["total"] for t in tokens.values())
    check(totals == 12500, "sum of totals unchanged (%d)" % totals)
    status, a = call(s2, "POST", "/authorizations", {"to_handle": "bob", "amount": 100},
                     tokens["ada"], "auth-key")
    check(status == 201 and a["authorization_id"].startswith("a_"), "new hold after upgrade")
    status, p = call(s2, "POST", "/authorizations/%s/capture" % a["authorization_id"], {},
                     tokens["bob"], "cap-key")
    check(status == 201 and p["authorization_id"] == a["authorization_id"]
          and p["payment_id"] not in {"p_1", lost_receipt["payment_id"]},
          "capture after upgrade, fresh payment id")
    status, first = call(s2, "GET", "/_test/export")
    call(s2, "POST", "/_test/import", first)
    status, second = call(s2, "GET", "/_test/export")
    check(first == second, "stage 2 export -> import -> export is stable")


def main():
    s1, s2 = os.environ["STAGE1_URL"], os.environ["STAGE2_URL"]
    export, tokens, lost, lost_receipt = drive_stage1(s1)
    if "--save" in sys.argv:
        path = sys.argv[sys.argv.index("--save") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"export": export, "tokens": tokens, "lost_body": lost,
                       "lost_receipt": lost_receipt}, fh, indent=1, sort_keys=True)
        print("saved", path)
    check_stage2(s2, export, tokens, lost, lost_receipt)
    print("PASS" if not failures else "FAIL (%d)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
