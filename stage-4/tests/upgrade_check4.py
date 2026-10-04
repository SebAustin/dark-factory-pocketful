#!/usr/bin/env python3
"""S4.4: populated stage-1, -2 and -3 exports imported into stage 4 (stdlib).

    STAGE1_URL=... STAGE2_URL=... STAGE3_URL=... STAGE4_URL=... \
        python3 stage-4/tests/upgrade_check4.py

Each frozen source performs every kind of write (stage 3 also corrections and a statement
snapshot), is exported and imported into stage 4. Checks: the stage 3 upgrade checks (sessions,
replays, pending requests, revision 1, history views, statements, linked immutability) with the
revision numbers the source left; imported corrections kept with correction_batch_id null;
refunds of imported payments (incl. a settlement member); a correction batch over a whole
imported settlement; stage-3 snapshot tokens absent (L10 known limitation); a stage-4 export ->
reset -> import round trip that restores snapshots. Exit 0 = pass.
"""
import os
import sys
import time

import upgrade_check3 as base
from upgrade_check3 import call, check

PW = base.PW


def drive_stage3(src):
    """Stage 2's writes on a frozen stage-3 service, plus a correction and a snapshot."""
    run = base.drive(src, 2)  # holds and every stage 1/2 write kind
    tok = run["tok"]
    plain = run["plain"]
    status, fixed = call(src, "POST", "/payments/%s/corrections" % plain,
                         {"expected_revision": 1, "amount": 650,
                          "effective_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(
                              time.time() - 5)), "reason": "stage 3 fix"}, tok["ada"], "s3-fix")
    check(status == 201, "stage 3: correction on the source")
    snap = call(src, "GET", "/statement", token=tok["ada"])[1]["snapshot"]
    run["export"] = call(src, "GET", "/_test/export")[1]
    run["s3_snapshot"] = snap
    run["s3_fix"] = fixed
    return run


def latest_revision(dst, token, pid):
    return call(dst, "GET", "/payments/%s/revisions" % pid, token=token)[1]["revisions"][-1]


def check_stage4(dst, run, stage):
    tag = "stage %d -> 4: " % stage
    base.check_target(dst, run, stage) if stage < 3 else check_stage3_source(dst, run)
    tok = run["tok"]
    exported = call(dst, "GET", "/_test/export")[1]
    payments = exported["state"]["payments"]
    for pid, p in payments.items():
        if p.get("refund_of", "missing") is not None or any(
                r.get("correction_batch_id") is not None for r in p["revisions"]):
            check(False, tag + "imported %s has refund_of / correction_batch_id null" % pid)
    check(True, tag + "refund_of and correction_batch_id null on %d imported payments"
          % len(payments))
    member = payments[run["member"]]
    receiver = member["to"][2:]
    status, refund = call(dst, "POST", "/payments/%s/refunds" % run["member"], {"amount": 1},
                          tok[receiver], "refund-member")
    check(status == 201 and refund["refund_of"] == run["member"]
          and refund["settlement_id"] is None, tag + "imported settlement member refunds")
    sid = member["settlement_id"]
    members = [pid for pid, p in payments.items() if p.get("settlement_id") == sid]
    items = [{"payment_id": pid, "expected_revision": latest_revision(
        dst, tok[payments[pid]["from"][2:]], pid)["revision"],
        "amount": max(payments[pid]["amount"] - 1, 1), "effective_at": member["created_at"],
        "reason": "upgrade batch"} for pid in members]
    status, body = call(dst, "POST", "/correction-batches", {"corrections": items}, tok["op"],
                        "batch-upgrade")
    check(status == 201 and len(body["revisions"]) == len(members),
          tag + "batch over the whole imported settlement (%d members)" % len(members))
    status, body = call(dst, "POST", "/correction-batches", {"corrections": items[:1]},
                        tok["op"], "batch-partial")
    check(status in (409, 422), tag + "partial or stale settlement batch refused (%s)" % status)
    if run.get("capture"):
        status, body = call(dst, "POST", "/payments/%s/refunds" % run["capture"],
                            {"amount": 1}, tok["bob"], "refund-capture")
        check(status == 201, tag + "imported capture refunds")
    snap = call(dst, "GET", "/statement?limit=200", token=tok["ada"])[1]
    first = call(dst, "GET", "/_test/export")[1]
    call(dst, "POST", "/_test/reset", base.fixture(stage if stage < 3 else 2))
    check(call(dst, "POST", "/_test/import", first)[0] == 204, tag + "stage-4 re-import")
    page = call(dst, "GET", "/statement?snapshot=%s&limit=200" % snap["snapshot"],
                token=tok["ada"])[1]
    check(page == snap, tag + "stage-4 snapshot pages identically after export/reset/import")
    check(call(dst, "GET", "/_test/export")[1] == first, tag + "stage-4 round trip stable")


def check_stage3_source(dst, run):
    """The stage 3 checks, with the correction the source already made."""
    tag = "stage 3 -> 4: "
    c = lambda *a, **k: call(dst, *a, **k)
    assert c("POST", "/_test/reset", base.fixture(2))[0] == 204
    dest_ada = c("POST", "/auth/login", {"email": "ada@example.com", "password": PW})[1]["token"]
    check(c("POST", "/_test/import", run["export"])[0] == 204, tag + "import 204")
    check(c("GET", "/me", token=dest_ada)[0] == 200, tag + "destination session survives (L5)")
    tok = run["tok"]
    for name, (m, path, body, who, k, receipt) in run["receipts"].items():
        status, again = c(m, path, body, tok[who], k)
        check(status == 200 and again == receipt, tag + "%s receipt replays verbatim" % name)
    revs = c("GET", "/payments/%s/revisions" % run["plain"], token=tok["ada"])[1]["revisions"]
    check(len(revs) == 2 and revs[1]["amount"] == 650 and revs[1]["reason"] == "stage 3 fix"
          and revs[1]["correction_batch_id"] is None, tag + "stage-3 correction kept")
    status, again = c("POST", "/payments/%s/corrections" % run["plain"],
                      {"expected_revision": 1, "amount": 650,
                       "effective_at": run["s3_fix"]["effective_at"],
                       "reason": "stage 3 fix"}, tok["ada"], "s3-fix")
    check(status == 200 and again == run["s3_fix"], tag + "stage-3 correction replays verbatim")
    status, _ = c("GET", "/statement?snapshot=%s" % run["s3_snapshot"], token=tok["ada"])
    check(status == 404, tag + "stage-3 snapshot token absent (L10 known limitation)")
    for h, t in tok.items():
        s = c("GET", "/statement?limit=200", token=t)[1]
        check(s["opening_balance"] + sum(e["delta"] for e in s["entries"])
              == s["closing_balance"] == c("GET", "/me", token=t)[1]["total"],
              tag + "statement of %s reconciles" % h)


def main():
    urls = [os.environ["STAGE%d_URL" % n] for n in (1, 2, 3, 4)]
    for stage in (1, 2, 3):
        run = drive_stage3(urls[2]) if stage == 3 else base.drive(urls[stage - 1], stage)
        check_stage4(urls[3], run, stage)
    print("PASS" if not base.failures else "FAIL (%d)" % len(base.failures))
    return 1 if base.failures else 0


if __name__ == "__main__":
    sys.exit(main())
