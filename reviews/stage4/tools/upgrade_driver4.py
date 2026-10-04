#!/usr/bin/env python3
"""Verifier stage-4 upgrade driver: stage-1/2/3 exports into stage 4, and stage-4 round trips with snapshots.

    python3 reviews/stage4/tools/upgrade_driver4.py populate --s1 URL --s2 URL --s3 URL --out DIR
    python3 reviews/stage4/tools/upgrade_driver4.py check --s4 URL --out DIR

populate: stages 1 and 2 use reviews/stage3/tools/upgrade_driver.py (same rich state). Stage 3 additionally gets corrections
  (amount changes, a zero reversal, a backdated effective_at), and its revisions and statements are recorded per payment and user.
check (per source): import 204; tokens; totals; idempotent replays with original bodies (incl. stage-3 corrections); revisions
  per payment identical to the source; each user's full statement identical to the source; settlement membership kept (members
  still linked_payment_immutable for single corrections); a refund of an imported plain payment works (201, refund_of set).
  Then a stage-4 round trip: a statement snapshot taken in stage 4, export -> reset -> import of that export -> the token pages
  identically (L10/L12; stage-4 exports carry snapshots).
Stdlib only; exit 1 on any failure.
"""
import argparse
import importlib.util
import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("ud3", HERE.parents[2] / "stage3" / "tools" / "upgrade_driver.py")
ud3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ud3)
call, user, Checks, PW = ud3.call, ud3.user, ud3.Checks, ud3.PW


def statement_full(base, tok):
    first = call(base, "GET", "/statement?limit=200", tok=tok)
    if first[0] != 200:
        return first
    b = first[1]
    entries, snap = list(b["entries"]), b.get("snapshot")
    while b.get("has_more"):
        s, b = call(base, "GET", "/statement?snapshot=%s&limit=200&offset=%d" % (snap, len(entries)), tok=tok)
        entries += b["entries"]
    return 200, {"opening": first[1]["opening_balance"], "closing": first[1]["closing_balance"], "entries": entries}


def populate_stage3(base, out):
    ud3.populate(base, "stage3", out, with_holds=True)
    meta = json.loads((out / "stage3.meta.json").read_text())
    tok = meta["tokens"]
    plain = [w for w in meta["writes"] if w["path"] == "/payments" and "burst" in w["key"]]
    now = datetime.now(timezone.utc)
    corrections = []
    for i, (w, amt, back) in enumerate(zip(plain, (50, 0, 120), (1, 30, 5))):
        p = w["response"]
        body = {"expected_revision": 1, "amount": amt, "effective_at": (now - timedelta(seconds=back)).isoformat(), "reason": "s3 fix %d" % i}
        st, r = call(base, "POST", "/payments/%s/corrections" % p["payment_id"], body, tok["ada"], "s3-corr-%d" % i)
        corrections.append({"pid": p["payment_id"], "status": st})
        if st == 201:
            meta["writes"].append({"path": "/payments/%s/corrections" % p["payment_id"], "key": "s3-corr-%d" % i, "body": body,
                                   "token": tok["ada"], "response": r})
    meta["revisions"] = {}
    for w in meta["writes"]:
        for p in ((w["response"] or {}).get("payments") or []) + ([w["response"]] if "payment_id" in (w["response"] or {}) and "from_handle" in w["response"] else []):
            s, r = call(base, "GET", "/payments/%s/revisions" % p["payment_id"], tok=tok[p["from_handle"]])
            if s == 200:
                meta["revisions"][p["payment_id"]] = r["revisions"]
    meta["statements"] = {h: statement_full(base, t)[1] for h, t in tok.items()}
    meta["balances"] = {h: call(base, "GET", "/me", tok=t)[1]["balance"] for h, t in tok.items()}
    export = call(base, "GET", "/_test/export")[1]
    (out / "stage3.export.json").write_text(json.dumps(export))
    (out / "stage3.meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print("stage3: corrections %s, %d revision lists, balances %s" % ([c["status"] for c in corrections], len(meta["revisions"]), meta["balances"]))


def strip_snap(stmt):
    return {k: v for k, v in stmt.items() if k != "snapshot"} if isinstance(stmt, dict) else stmt


def check(s4, stage, out, chk):
    export = json.loads((out / ("%s.export.json" % stage)).read_text())
    meta = json.loads((out / ("%s.meta.json" % stage)).read_text())
    call(s4, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [user("u_zz", "zz", 1)]})
    chk("[%s] import -> 204" % stage, call(s4, "POST", "/_test/import", export)[0] == 204)
    tok, bal = meta["tokens"], meta["balances"]
    me = {h: call(s4, "GET", "/me", tok=t) for h, t in tok.items()}
    chk("[%s] tokens work, totals equal the source" % stage, all(r[0] == 200 and r[1]["total"] == bal[h] for h, r in me.items()))
    bad = [w["key"] for w in meta["writes"] if call(s4, "POST", w["path"], w["body"], w["token"], w["key"]) != (200, w["response"])]
    chk("[%s] %d idempotent writes replay their original body" % (stage, len(meta["writes"])), not bad, str(bad[:4]))
    if "revisions" in meta:
        sender = {}
        for w in meta["writes"]:
            r = w["response"] or {}
            for p in (r.get("payments") or []) + ([r] if "from_handle" in r else []):
                sender[p["payment_id"]] = tok[p["from_handle"]]
        keep = ("revision", "amount", "effective_at", "recorded_at", "reason")
        norm = lambda revs: [{k: x[k] for k in keep} for x in revs]
        diff = []
        for pid, revs in meta["revisions"].items():
            s_, r_ = call(s4, "GET", "/payments/%s/revisions" % pid, tok=sender[pid])
            if s_ != 200 or norm(r_["revisions"]) != norm(revs):
                diff.append((pid, s_))
        chk("[%s] revision histories identical to the source (%d payments)" % (stage, len(meta["revisions"])), not diff, str(diff[:4]))
        added = ("refund_of", "correction_batch_id")             # fields stage 4 adds by spec

        def strip(stmt):
            out_ = dict(stmt)
            out_["entries"] = [{k: ({kk: vv for kk, vv in v.items() if kk not in added} if k == "payment" else v)
                                for k, v in e.items() if k not in added} for e in stmt["entries"]]
            return out_
        sdiff = [h for h, st in meta["statements"].items() if strip(statement_full(s4, tok[h])[1]) != strip(st)]
        chk("[%s] every user's full statement identical to the source (stage-4 added fields ignored)" % stage, not sdiff, str(sdiff))
    members = meta.get("settlement_members", [])
    sender = {}
    for w in meta["writes"]:
        for p in ((w["response"] or {}).get("payments") or []):
            sender[p["payment_id"]] = tok[p["from_handle"]]
    eff = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    lk = [call(s4, "POST", "/payments/%s/corrections" % m, {"expected_revision": 1, "amount": 1, "effective_at": eff, "reason": "x"}, sender.get(m, tok["op"]), "lk-" + m) for m in members]
    chk("[%s] settlement members still linked (single correction -> 422 linked_payment_immutable)" % stage,
        all(r[0] == 422 and r[1]["error"]["code"] == "linked_payment_immutable" for r in lk), str([r[0] for r in lk]))
    plain = next(w["response"] for w in meta["writes"] if w["path"] == "/payments" and "priv" in w["key"])   # bob -> cy 250
    s, r = call(s4, "POST", "/payments/%s/refunds" % plain["payment_id"], {"amount": 10}, tok["cy"], "rf-" + stage)
    chk("[%s] refund of an imported payment -> 201 with refund_of" % stage, s == 201 and r.get("refund_of") == plain["payment_id"], str((s, r))[:160])
    # stage-4 round trip with a live snapshot
    s, st = call(s4, "GET", "/statement?limit=3", tok=tok["ada"])
    snap, page0 = st["snapshot"], call(s4, "GET", "/statement?snapshot=%s&limit=200" % st["snapshot"], tok=tok["ada"])[1]
    exp4 = call(s4, "GET", "/_test/export")[1]
    call(s4, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [user("u_zz", "zz", 1)]})
    imp = call(s4, "POST", "/_test/import", exp4)[0]
    page1 = call(s4, "GET", "/statement?snapshot=%s&limit=200" % snap, tok=tok["ada"])
    chk("[%s] stage-4 export -> reset -> import keeps the snapshot (pages identical)" % stage, imp == 204 and page1 == (200, page0), str(page1[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("populate", "check"))
    for k in ("s1", "s2", "s3", "s4"):
        ap.add_argument("--" + k)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if a.mode == "populate":
        if a.s1:
            ud3.populate(a.s1.rstrip("/"), "stage1", out, with_holds=False)
        if a.s2:
            ud3.populate(a.s2.rstrip("/"), "stage2", out, with_holds=True)
        if a.s3:
            populate_stage3(a.s3.rstrip("/"), out)
        return 0
    chk = Checks()
    for stage in ("stage1", "stage2", "stage3"):
        if (out / ("%s.export.json" % stage)).exists():
            check(a.s4.rstrip("/"), stage, out, chk)
    return 0 if chk.ok else 1


if __name__ == "__main__":
    sys.exit(main())
