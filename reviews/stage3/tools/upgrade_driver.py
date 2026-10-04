#!/usr/bin/env python3
"""Verifier upgrade driver for stage 3: populate frozen stage-1 / stage-2 services with rich state,
export them, import into a stage-3 service and check what survives.

    python3 reviews/stage3/tools/upgrade_driver.py populate --s1 http://127.0.0.1:18427 --s2 http://127.0.0.1:18442 --out /tmp/upg
    python3 reviews/stage3/tools/upgrade_driver.py check --s3 http://127.0.0.1:18450 --out /tmp/upg

`populate` writes, per source stage, <out>/<stage>.export.json (the unchanged export) and <out>/<stage>.meta.json:
the tokens, the idempotent bodies and their original responses, the failed keys, the expected balances per user,
the settlement member ids and the capture payment ids. `check` imports each export into stage 3 (reset in between) and verifies:
  - import 204; every source token still authenticates; /me totals equal the source balances; sum of totals = source sum
  - every recorded idempotent write replays 200 with a JSON-equal original body; failed keys are reusable (non-409)
  - /statement (no params) per user: opening + sum(delta) == closing, oldest first, balance_after chains, entries are
    exactly that user's payments; closing == current total
  - /me?as_of=<each payment's created_at> per user sums to the seeded total over all users (historical views)
  - corrections: settlement members and captures -> 422 linked_payment_immutable; an ordinary payment by its sender
    with expected_revision 1 -> 201, and a replay -> 200 with the same body; revisions list starts with revision 1, reason ""
Stdlib only. Exit 1 if any check fails.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PW = "correct horse"
TIMEOUT = 20


def call(base, method, path, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(base + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = r.read()
            return r.status, json.loads(d) if d else None
    except urllib.error.HTTPError as e:
        d = e.read()
        try:
            return e.code, json.loads(d) if d else None
        except ValueError:
            return e.code, {"raw": d[:200].decode("latin-1")}


def user(i, h, bal):
    return {"id": i, "email": h + "@e.com", "password": PW, "display_name": h.title(), "handle": h, "balance": bal}


def iso(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


class Recorder:
    """Keeps every idempotent write (path, key, body, token, original response) for replay after import."""

    def __init__(self, base):
        self.base, self.writes, self.failed = base, [], []

    def write(self, path, body, tok, key, expect_ok=True):
        status, resp = call(self.base, "POST", path, body, tok, key)
        if status in (200, 201):
            self.writes.append({"path": path, "key": key, "body": body, "token": tok, "response": resp})
        else:
            self.failed.append({"path": path, "key": key, "body": body, "token": tok, "status": status})
        if expect_ok and status not in (200, 201):
            print("  note: %s %s -> %s %s" % (path, key, status, json.dumps(resp)[:120]))
        return status, resp


def populate_common(base, rec, tok, stage):
    """Payments (incl. same-second bursts), requests in every status, a zero-share split, a settlement, a failed key."""
    p = lambda f, t, a, k, vis="public", note="": rec.write("/payments", {"to_handle": t, "amount": a, "note": note, "visibility": vis}, tok[f], "%s-%s" % (stage, k))
    for i in range(4):                                        # same-second burst
        p("ada", "bob", 100 + i, "burst%d" % i, note="burst %d ☕" % i)
    p("bob", "cy", 250, "priv", vis="private", note="private one")
    p("cy", "ada", 1, "tiny")
    rq = lambda r, payer, a, k: rec.write("/requests", {"payer_handle": payer, "amount": a, "note": "rq " + k}, tok[r], "%s-rq-%s" % (stage, k))
    ids = {k: rq("bob", "ada", a, k)[1]["request_id"] for k, a in (("pay", 300), ("dec", 7), ("can", 9), ("pend", 50000))}
    rec.write("/requests/%s/pay" % ids["pay"], {"visibility": "private"}, tok["ada"], "%s-rqpay" % stage)
    call(base, "POST", "/requests/%s/decline" % ids["dec"], None, tok["ada"])
    call(base, "POST", "/requests/%s/cancel" % ids["can"], None, tok["bob"])
    sp = rec.write("/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"], "note": "zero shares"}, tok["ada"], "%s-split" % stage)[1]
    zero = sp["requests"][0]["request_id"]
    rec.write("/requests/%s/pay" % zero, {}, tok["bob"], "%s-zeropay" % stage)
    st = rec.write("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "op", "amount": 70},
                                                   {"from_handle": "op", "to_handle": "cy", "amount": 30}]}, tok["op"], "%s-settle" % stage)[1]
    rec.write("/payments", {"to_handle": "bob", "amount": 10 ** 9}, tok["cy"], "%s-failed" % stage, expect_ok=False)
    return {"pending_request": ids["pend"], "settlement_members": [m["payment_id"] for m in st["payments"]]}


def populate_holds(base, rec, tok, stage):
    """Stage 2 only: authorizations captured (partial final), extended capture chain, voided, expired, open."""
    a = lambda amt, k: rec.write("/authorizations", {"to_handle": "bob", "amount": amt, "note": "hold " + k}, tok["ada"], "%s-auth-%s" % (stage, k))[1]["authorization_id"]
    cap = lambda aid, body, k: rec.write("/authorizations/%s/capture" % aid, body, tok["bob"], "%s-cap-%s" % (stage, k))[1]
    a1, a2, a3, a4 = a(500, "final"), a(900, "chain"), a(40, "void"), a(60, "open")
    captures = [cap(a1, {"amount": 300}, "final")["payment_id"],
                cap(a2, {"amount": 200, "final": False}, "chain1")["payment_id"],
                cap(a2, {"amount": 100, "final": False}, "chain2")["payment_id"]]
    call(base, "POST", "/authorizations/%s/void" % a3, None, tok["ada"])
    return {"captures": captures, "open_hold": a4}


def populate(base, stage, out, with_holds):
    users = [user("u_ada", "ada", 20000), user("u_bob", "bob", 5000), user("u_cy", "cy", 1000), user("u_op", "op", 0)]
    fixture = {"currency": "EUR", "minor_units": 2, "users": users, "settlement_operator_ids": ["u_op"],
               "payments": [{"id": "p_seed", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 5, "note": "seeded"}]}
    if with_holds:
        fixture["authorization_ttl_seconds"] = 2               # holds created now expire quickly (one stays expired)
    assert call(base, "POST", "/_test/reset", fixture)[0] == 204, "reset failed on " + base
    tok = {u["handle"]: call(base, "POST", "/auth/login", {"email": u["email"], "password": PW})[1]["token"] for u in users}
    tok["new"] = call(base, "POST", "/auth/signup", {"email": "new@e.com", "password": PW, "display_name": "New"})[1]["token"]
    rec = Recorder(base)
    meta = populate_common(base, rec, tok, stage)
    if with_holds:
        meta.update(populate_holds(base, rec, tok, stage))
        time.sleep(3)                                          # the open 2 s hold expires before export
    balances = {h: call(base, "GET", "/me", tok=t)[1]["balance"] for h, t in tok.items()}
    export = call(base, "GET", "/_test/export")[1]
    out.mkdir(parents=True, exist_ok=True)
    (out / ("%s.export.json" % stage)).write_text(json.dumps(export))
    meta.update({"tokens": tok, "balances": balances, "writes": rec.writes, "failed": rec.failed})
    (out / ("%s.meta.json" % stage)).write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print("%s: %d writes, %d failed keys, balances %s" % (stage, len(rec.writes), len(rec.failed), balances))


class Checks:
    def __init__(self):
        self.ok = True

    def __call__(self, name, cond, detail=""):
        self.ok &= bool(cond)
        print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


def statement_all(base, tok, extra=""):
    """All pages of a statement (follows offset; uses the snapshot when the service returns one)."""
    first = call(base, "GET", "/statement?limit=200" + extra, tok=tok)
    if first[0] != 200:
        return first, []
    body, entries = first[1], list(first[1].get("entries", []))
    snap, offset = body.get("snapshot"), len(entries)
    while body.get("has_more"):
        q = "/statement?snapshot=%s&limit=200&offset=%d" % (snap, offset) if snap else "/statement?limit=200&offset=%d%s" % (offset, extra)
        status, body = call(base, "GET", q, tok=tok)
        if status != 200:
            return (status, body), entries
        entries += body["entries"]
        offset += len(body["entries"])
    return first, entries


def check_stage(s3, stage, out, chk):
    export = json.loads((out / ("%s.export.json" % stage)).read_text())
    meta = json.loads((out / ("%s.meta.json" % stage)).read_text())
    call(s3, "POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [user("u_zz", "zz", 1)]})
    chk("[%s] import -> 204" % stage, call(s3, "POST", "/_test/import", export)[0] == 204)
    tok, bal = meta["tokens"], meta["balances"]
    me = {h: call(s3, "GET", "/me", tok=t) for h, t in tok.items()}
    chk("[%s] every source token authenticates" % stage, all(r[0] == 200 for r in me.values()))
    chk("[%s] totals equal source balances" % stage, all(me[h][1].get("total", me[h][1].get("balance")) == bal[h] for h in tok),
        str({h: (me[h][1] or {}).get("total") for h in tok}))
    bad = [w["key"] for w in meta["writes"] if call(s3, "POST", w["path"], w["body"], w["token"], w["key"]) != (200, w["response"])]
    chk("[%s] %d idempotent writes replay 200 with the original body" % (stage, len(meta["writes"])), not bad, str(bad[:5]))
    reuse = [f["key"] for f in meta["failed"] if call(s3, "POST", f["path"], dict(f["body"], amount=1), f["token"], f["key"])[0] == 409]
    chk("[%s] failed keys reusable" % stage, not reuse, str(reuse))
    seeded_total = sum(bal.values())
    current = {h: call(s3, "GET", "/me", tok=t)[1]["total"] for h, t in tok.items()}   # after the failed-key reuse above
    instants = set()
    for h, t in tok.items():
        first, entries = statement_all(s3, t)
        if first[0] != 200:
            chk("[%s] statement %s" % (stage, h), False, str(first)[:160])
            continue
        b = first[1]
        running, chain_ok = b["opening_balance"], True
        for e in entries:
            running += e["delta"]
            chain_ok &= e["balance_after"] == running
            instants.add(e.get("effective_at") or e["payment"]["created_at"])
        order = [(e.get("effective_at") or e["payment"]["created_at"], e["payment"]["payment_id"]) for e in entries]
        chk("[%s] statement %s: opening+deltas=closing=current, chained, oldest first" % (stage, h),
            chain_ok and running == b["closing_balance"] == current[h] and order == sorted(order),
            "opening %s closing %s current %s n=%d" % (b["opening_balance"], b["closing_balance"], current[h], len(entries)))
    views = []
    for t_ in sorted(instants):
        q = urllib.parse.quote(t_, safe="")
        views.append((t_, sum(call(s3, "GET", "/me?as_of=" + q, tok=t)[1].get("balance", 0) for t in tok.values())))
    chk("[%s] sum of balances = seeded total in every as_of view (%d instants)" % (stage, len(views)),
        views and all(v == seeded_total for _, v in views), str([v for v in views if v[1] != seeded_total][:3]))
    corr = lambda pid, t, k, amt=1: call(s3, "POST", "/payments/%s/corrections" % pid,
                                         {"expected_revision": 1, "amount": amt, "effective_at": iso(-1), "reason": "verifier"}, t, k)
    sender_tok = {}
    for w in meta["writes"]:
        r = w["response"] or {}
        for p in (r.get("payments") or []) + ([r] if "payment_id" in r else []):
            if "from_handle" in p:
                sender_tok[p["payment_id"]] = tok[p["from_handle"]]
    linked = meta.get("settlement_members", []) + meta.get("captures", [])
    res = {pid: corr(pid, sender_tok.get(pid, tok["ada"]), "lk-" + pid) for pid in linked}
    chk("[%s] settlement members and captures, corrected by their sender -> 422 linked_payment_immutable" % stage,
        all(r[0] == 422 and (r[1] or {}).get("error", {}).get("code") == "linked_payment_immutable" for r in res.values()),
        str({k: (v[0], (v[1] or {}).get("error", {}).get("code")) for k, v in res.items()}))
    plain = next(w["response"] for w in meta["writes"] if w["path"] == "/payments" and "burst" in w["key"])
    first = corr(plain["payment_id"], tok["ada"], "fix-1", amt=plain["amount"] - 1)
    again = corr(plain["payment_id"], tok["ada"], "fix-1", amt=plain["amount"] - 1)
    revs = call(s3, "GET", "/payments/%s/revisions" % plain["payment_id"], tok=tok["ada"])
    chk("[%s] correction 201, replay 200 identical, revisions start with rev 1 reason ''" % stage,
        first[0] == 201 and again == (200, first[1]) and revs[0] == 200 and revs[1]["revisions"][0]["revision"] == 1
        and revs[1]["revisions"][0]["reason"] == "", "%s %s" % (first[0], again[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("populate", "check"))
    ap.add_argument("--s1")
    ap.add_argument("--s2")
    ap.add_argument("--s3")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    if a.mode == "populate":
        if a.s1:
            populate(a.s1.rstrip("/"), "stage1", out, with_holds=False)
        if a.s2:
            populate(a.s2.rstrip("/"), "stage2", out, with_holds=True)
        return 0
    chk = Checks()
    for stage in ("stage1", "stage2"):
        if (out / ("%s.export.json" % stage)).exists():
            check_stage(a.s3.rstrip("/"), stage, out, chk)
    return 0 if chk.ok else 1


if __name__ == "__main__":
    sys.exit(main())
