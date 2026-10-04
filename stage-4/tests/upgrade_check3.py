#!/usr/bin/env python3
"""S3.5: populated stage-1 and stage-2 exports imported into stage 3 (stdlib).

    STAGE1_URL=... STAGE2_URL=... STAGE3_URL=... python3 stage-3/tests/upgrade_check3.py

For each source (the team's frozen stage-1 and stage-2 services) it performs every kind of write
(payments incl. a lost-response retry, requests paid/pending/declined, a split, a settlement, and
on stage 2 holds that stay open, are captured partly/finally, voided and expire), exports, then on
stage 3: imports, signs a destination session in before the import (L5/D-52), and checks tokens,
receipts replaying verbatim, pending requests payable, revision 1 for every payment, statements
(opening + Σ delta = closing; entries = the caller's payments), /me history (Σ totals = seeded
total at many instants, available = total - held), corrections on an imported plain payment,
settlement members and captures immutable, and a stage-3 export -> import -> export round trip.
Exit 0 = pass.
"""
import http.client
import json
import os
import sys
import time
from urllib.parse import quote, urlsplit

PW = "correct horse"
failures = []


def call(base, method, path, body=None, token=None, key=None):
    u = urlsplit(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=20)
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
    print(("ok   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)


def fixture(stage):
    users = [{"id": "u_%s" % h, "email": "%s@example.com" % h, "password": PW,
              "display_name": h.title(), "handle": h, "balance": b}
             for h, b in (("ada", 10000), ("bob", 2500), ("cy", 0), ("op", 0))]
    f = {"currency": "EUR", "minor_units": 2, "users": users,
         "payments": [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                       "amount": 500, "note": "seeded", "visibility": "public"}],
         "requests": [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                       "amount": 120, "note": "taxi", "status": "pending"}],
         "settlement_operator_ids": ["u_op"]}
    if stage == 2:
        f["authorization_ttl_seconds"] = 2
    return f


def drive(src, stage):
    """Every write kind on a frozen source service; returns what the checks need."""
    c = lambda *a, **k: call(src, *a, **k)
    assert c("POST", "/_test/reset", fixture(stage))[0] == 204
    tok = {h: c("POST", "/auth/login", {"email": h + "@example.com",
                                        "password": PW})[1]["token"]
           for h in ("ada", "bob", "cy", "op")}
    receipts = {}
    lost = {"to_handle": "bob", "amount": 700, "note": "lost response", "visibility": "private"}
    receipts["lost"] = ("POST", "/payments", lost, "ada", "lost-key",
                        c("POST", "/payments", lost, tok["ada"], "lost-key")[1])
    plain = receipts["lost"][5]["payment_id"]
    rq = c("POST", "/requests", {"payer_handle": "cy", "amount": 50}, tok["bob"], "rq-a")[1]
    c("POST", "/payments", {"to_handle": "cy", "amount": 300}, tok["ada"], "fund-cy")
    receipts["pay"] = ("POST", "/requests/%s/pay" % rq["request_id"], {}, "cy", "pay-a",
                       c("POST", "/requests/%s/pay" % rq["request_id"], {}, tok["cy"],
                         "pay-a")[1])
    rq2 = c("POST", "/requests", {"payer_handle": "ada", "amount": 70}, tok["cy"], "rq-b")[1]
    c("POST", "/requests/%s/decline" % rq2["request_id"], {}, tok["ada"])
    receipts["split"] = ("POST", "/splits", {"amount": 900, "participant_handles":
                                             ["ada", "bob", "cy"], "note": "dinner"},
                         "ada", "split-a", None)
    receipts["split"] = receipts["split"][:5] + (c(*receipts["split"][:3], tok["ada"],
                                                   "split-a")[1],)
    st = c("POST", "/settlements", {"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 40},
        {"from_handle": "cy", "to_handle": "ada", "amount": 10}]}, tok["op"], "settle-a")[1]
    receipts["settle"] = ("POST", "/settlements", {"transfers": [
        {"from_handle": "bob", "to_handle": "cy", "amount": 40},
        {"from_handle": "cy", "to_handle": "ada", "amount": 10}]}, "op", "settle-a", st)
    member = st["payments"][0]["payment_id"]
    capture = None
    if stage == 2:
        made = {}
        for name, amount in (("partial", 200), ("final", 300), ("void", 400), ("expire", 60)):
            made[name] = c("POST", "/authorizations", {"to_handle": "bob", "amount": amount},
                           tok["ada"], "auth-" + name)[1]["authorization_id"]
        c("POST", "/authorizations/%s/capture" % made["partial"],
          {"amount": 50, "final": False}, tok["bob"], "cap-1")
        capture = c("POST", "/authorizations/%s/capture" % made["final"], {"amount": 120},
                    tok["bob"], "cap-2")[1]["payment_id"]
        c("POST", "/authorizations/%s/void" % made["void"], {}, tok["ada"])
        time.sleep(2.3)  # the remaining open holds pass their deadline
        made["open"] = c("POST", "/authorizations", {"to_handle": "cy", "amount": 25},
                         tok["ada"], "auth-open")[1]["authorization_id"]
    status, export = c("GET", "/_test/export")
    check(status == 200, "stage %d: export" % stage)
    total = sum(u["balance"] for u in fixture(stage)["users"])
    return {"export": export, "tok": tok, "receipts": receipts, "plain": plain,
            "member": member, "capture": capture, "total": total}


def q(params):
    return "&".join("{}={}".format(k, quote(str(v), safe="")) for k, v in params.items())


def check_target(dst, run, stage):
    c = lambda *a, **k: call(dst, *a, **k)
    tag = "stage %d -> 3: " % stage
    assert c("POST", "/_test/reset", fixture(stage))[0] == 204
    dest_ada = c("POST", "/auth/login", {"email": "ada@example.com", "password": PW})[1]["token"]
    check(c("POST", "/_test/import", run["export"])[0] == 204, tag + "import 204")
    tok = run["tok"]
    check(c("GET", "/me", token=dest_ada)[0] == 200,
          tag + "destination session of a user in the export survives (L5)")
    for h, t in tok.items():
        check(c("GET", "/me", token=t)[0] == 200, tag + "exported token of %s works" % h)
    for name, (m, path, body, who, k, receipt) in run["receipts"].items():
        status, again = c(m, path, body, tok[who], k)
        check(status == 200 and again == receipt, tag + "%s receipt replays verbatim" % name)
    status, pending = c("GET", "/requests?direction=incoming&status=pending", token=tok["ada"])
    for r in pending["requests"]:
        s, paid = c("POST", "/requests/%s/pay" % r["request_id"], {}, tok["ada"],
                    "late-" + r["request_id"])
        check(s == 201, tag + "pending request %s payable" % r["request_id"])
    export = c("GET", "/_test/export")[1]
    for pid, p in export["state"]["payments"].items():
        r1 = p["revisions"][0]
        if not (r1["revision"] == 1 and r1["amount"] == p["amount"]
                and r1["effective_at"] == r1["recorded_at"] == p["created_at"]
                and r1["reason"] == ""):
            check(False, tag + "revision 1 of %s" % pid)
    check(True, tag + "revision 1 = the payment as made, for %d payments"
          % len(export["state"]["payments"]))
    instants_ = sorted({p["created_at"] for p in export["state"]["payments"].values()})
    probes = ["1970-01-01T00:00:00Z"] + instants_ + ["2999-01-01T00:00:00Z"]
    for at in probes:
        views = [c("GET", "/me?" + q({"as_of": at}), token=t)[1] for t in tok.values()]
        ok = sum(v["total"] for v in views) == run["total"] + 0 and all(
            v["available"] == v["total"] - v["held"] and v["available"] >= 0 for v in views)
        if not ok:
            check(False, tag + "views at %s: %s" % (at, views))
    check(True, tag + "Σ totals = seeded total and available >= 0 at %d instants" % len(probes))
    for h, t in tok.items():
        s = c("GET", "/statement?limit=200", token=t)[1]
        uid = "u_" + h
        ok = s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"]
        ok = ok and all(uid in (e["payment"]["from_user_id"], e["payment"]["to_user_id"])
                        for e in s["entries"])
        check(ok and s["closing_balance"] == c("GET", "/me", token=t)[1]["total"],
              tag + "statement of %s reconciles" % h)
    plain = export["state"]["payments"][run["plain"]]
    s, r = c("POST", "/payments/%s/corrections" % run["plain"],
             {"expected_revision": 1, "amount": plain["amount"] - 100,
              "effective_at": plain["created_at"], "reason": "upgrade check"},
             tok["ada"], "fix-plain")
    check(s == 201 and r["revision"] == 2, tag + "imported plain payment corrects")
    for name in ("member", "capture"):
        pid = run[name]
        if pid is None:
            continue
        sender = export["state"]["payments"][pid]["from"][2:]
        s, r = c("POST", "/payments/%s/corrections" % pid,
                 {"expected_revision": 1, "amount": 1,
                  "effective_at": "2020-01-01T00:00:00Z", "reason": "x"},
                 tok[sender], "fix-" + name)
        check(s == 422 and r["error"]["code"] == "linked_payment_immutable",
              tag + "imported %s is linked_payment_immutable" % name)
    first = c("GET", "/_test/export")[1]
    c("POST", "/_test/import", first)
    check(c("GET", "/_test/export")[1] == first, tag + "stage-3 round trip stable")


def main():
    s1, s2, s3 = (os.environ[k] for k in ("STAGE1_URL", "STAGE2_URL", "STAGE3_URL"))
    for stage, src in ((1, s1), (2, s2)):
        check_target(s3, drive(src, stage), stage)
    print("PASS" if not failures else "FAIL (%d)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
