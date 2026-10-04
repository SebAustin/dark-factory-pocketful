#!/usr/bin/env python3
"""A small stand-in service for self-testing diff_run.py (never part of the product).

It answers the stage 3 history endpoints from the reference model, so a clean run proves the tool's plumbing
agrees with itself; BUG=<name> plants one divergence so the tool can be shown to catch it:

  asof_exclusive    GET /me counts only effective_at < as_of
  ignore_known_at   known_at is ignored by /me and /statement
  stmt_closed_to    the statement window is closed at `to`
  order_created     entries ordered by original created_at instead of effective_at
  page_balance      balance_after restarts at each page's opening
  snapshot_live     snapshot paging recomputes from the current state
  avail_ignores     available ignores holds
  hold_boundary     a hold is released one instant late (as_of == expires_at still held)
  no_stale          stale expected_revision is not checked (lost updates)
  no_overdraft      historical_overdraft is never raised
  replay_latest     a correction replay returns the latest revision, not the original
  zero_hidden       zero-amount revisions are left out of statements
  no_echo           known_at is not echoed
  opening_moves     corrections change the opening balance
Run: PORT=18390 BUG= python3 fake_service.py
"""
import itertools
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from model import NEG, POS, UTC, Model, fmt, parse, parse_query

BUG = os.environ.get("BUG", "")
LOCK = threading.RLock()
S = {}


_LAST = [datetime.min.replace(tzinfo=UTC)]


def now():
    """D-41: one monotonic microsecond clock; every call returns a strictly later instant."""
    with LOCK:
        t = max(datetime.now(UTC), _LAST[0] + timedelta(microseconds=1))
        _LAST[0] = t
        return t


def iso(t):
    return t.astimezone(UTC).isoformat(timespec="microseconds")


class Err(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def reset(fx):
    S.clear()
    ids = itertools.count(1)
    S.update(users={}, handles={}, tokens={}, ids=ids, keys={}, snaps={}, model=None, ttl=fx.get("authorization_ttl_seconds", 600),
             ops=set(fx.get("settlement_operator_ids", [])), auths={}, emails={})
    ending, seeded = {}, []
    for u in fx["users"]:
        S["users"][u["id"]] = u
        S["handles"][u["handle"]] = u["id"]
        S["emails"][u["email"]] = u["id"]
        ending[u["id"]] = u["balance"]
    t0 = now()
    for p in fx.get("payments", []):
        seeded.append((p["id"], p["from_user_id"], p["to_user_id"], p["amount"], parse(p["created_at"]) if p.get("created_at") else t0, p.get("visibility", "public")))
    S["model"] = Model.from_seed(ending, seeded)
    for a in fx.get("authorizations", []):
        created = parse(a["created_at"]) if a.get("created_at") else t0
        S["model"].add_auth(a["id"], a["from_user_id"], a["to_user_id"], a["amount"], created, parse(a["expires_at"]))


def pay_view(pay, rev=None):
    rev = rev or pay.revs[0]
    return {"payment_id": pay.id, "from_user_id": pay.frm, "to_user_id": pay.to, "amount": rev.amount, "currency": "EUR", "note": "",
            "visibility": pay.visibility, "request_id": None, "settlement_id": None, "created_at": iso(pay.created_at)}


def auth_view(a):
    closed = None
    if a.close:
        closed = iso(a.close[1])
    elif a.expires_at <= now():
        closed = iso(a.expires_at)
    status = a.close[0] if a.close else ("expired" if a.expires_at <= now() else "open")
    return {"authorization_id": a.id, "from_user_id": a.frm, "to_user_id": a.to, "amount": a.amount, "status": status, "closed_at": closed,
            "created_at": iso(a.created_at), "expires_at": iso(a.expires_at)}


def instant(q, name):
    if name not in q:
        return None
    try:
        return parse_query(q[name][-1])
    except ValueError:
        raise Err(422, "validation_failed")


def check_correction(pid, user, body):
    model = S["model"]
    if not all(k in body for k in ("expected_revision", "amount", "effective_at", "reason")):
        raise Err(422, "validation_failed")
    eff = parse(body["effective_at"])
    if eff > now():
        raise Err(422, "validation_failed")
    result = model.correction_result(pid, user, body["expected_revision"], body["amount"], eff, now())
    if BUG == "no_stale" and result == "stale_revision":
        result = "ok"
    if BUG == "no_overdraft" and result == "historical_overdraft":
        result = "ok"
    if result == "404":
        raise Err(404, "not_found")
    if result == "403":
        raise Err(403, "forbidden")
    if result == "linked_payment_immutable":
        raise Err(422, result)
    if result != "ok":
        raise Err(409, result)
    return model.payments[pid], eff


def me(user, q):
    model = S["model"]
    as_of, known = instant(q, "as_of"), instant(q, "known_at")
    if BUG == "ignore_known_at":
        known = None
    t0 = now()
    if BUG == "asof_exclusive" and as_of is not None:
        total = model.total(user, as_of, known, inclusive=False)
        held = model.held(user, as_of, known)
        out = {"balance": total, "total": total, "available": total - held, "held": held}
    else:
        out = model.me(user, as_of, known, t0)
    if BUG == "avail_ignores":
        out["available"] = out["total"]
        out["held"] = 0
    if BUG == "hold_boundary" and as_of is not None:
        held = model.held(user, as_of - timedelta(microseconds=1), known)
        out["held"], out["available"] = held, out["total"] - held
    out.update(user_id=user, currency="EUR", minor_units=2)
    if "as_of" in q:
        out["as_of"] = q["as_of"][-1]
    if "known_at" in q and BUG != "no_echo":
        out["known_at"] = q["known_at"][-1]
    return out


def full_statement(user, frm, to, known):
    model = S["model"]
    if BUG == "stmt_closed_to" and to is not None:
        to = to + timedelta(microseconds=1)
    if BUG == "order_created":
        full = model.statement(user, frm, to, known, now())
        full["entries"].sort(key=lambda e: (model.payments[e["id"]].created_at, e["id"]))
        return full
    full = model.statement(user, frm, to, known, now())
    if BUG == "zero_hidden":
        full["entries"] = [e for e in full["entries"] if e["delta"] != 0]
    return full


def entry_json(model, e):
    pay = model.payments[e["id"]]
    view = pay_view(pay)
    view["amount"] = e["amount"]
    return {"payment": view, "delta": e["delta"], "balance_after": e["balance_after"], "revision": e["revision"],
            "effective_at": iso(e["effective_at"]), "recorded_at": iso(e["recorded_at"])}


def page_of(user, full, limit, offset):
    model = S["model"]
    entries = full["entries"][offset:offset + limit]
    out = [entry_json(model, e) for e in entries]
    if BUG == "page_balance" and offset and offset < len(full["entries"]):
        base = full["entries"][offset - 1]["balance_after"]
        drift = base - (full["entries"][offset]["balance_after"] - full["entries"][offset]["delta"])
        for e in out:
            e["balance_after"] += drift + 1
    return {"opening_balance": full["opening_balance"], "entries": out, "closing_balance": full["closing_balance"], "has_more": offset + limit < len(full["entries"])}


def statement(user, q):
    if "snapshot" in q:
        if any(k in q for k in ("from", "to", "known_at")):
            raise Err(422, "validation_failed")
        snap = S["snaps"].get(q["snapshot"][0])
        if snap is None or snap["user"] != user:
            raise Err(404, "not_found")
        limit, offset = int(q.get("limit", ["50"])[0]), int(q.get("offset", ["0"])[0])
        full = snap["full"]
        if BUG == "snapshot_live":
            full = full_statement(user, snap["from"], snap["to"], snap["known"])
        out = page_of(user, full, limit, offset)
        out["snapshot"] = q["snapshot"][0]
        return out
    frm, to, known = instant(q, "from"), instant(q, "to"), instant(q, "known_at")
    if BUG == "ignore_known_at":
        known = None
    limit, offset = int(q.get("limit", ["50"])[0]), int(q.get("offset", ["0"])[0])
    if not 1 <= limit <= 200 or offset < 0:
        raise Err(422, "validation_failed")
    if frm is not None and to is not None and frm > to:
        raise Err(422, "validation_failed")
    to_eff = to if to is not None else now()
    full = full_statement(user, frm, to_eff, known)
    token = uuid.uuid4().hex
    S["snaps"][token] = {"user": user, "full": full, "from": frm, "to": to_eff, "known": known}
    out = page_of(user, full, limit, offset)
    out["snapshot"] = token
    if "known_at" in q and BUG != "no_echo":
        out["known_at"] = q["known_at"][-1]
    return out


def handle(method, path, q, body, hdr):
    model = S.get("model")
    if path == "/_test/reset":
        reset(body)
        return 204, None
    if path == "/auth/login":
        uid = S["emails"].get(body.get("email"))
        if uid and S["users"][uid]["password"] == body.get("password"):
            tok = uuid.uuid4().hex
            S["tokens"][tok] = uid
            return 200, {"user_id": uid, "token": tok}
        raise Err(401, "unauthenticated")
    token = hdr.get("Authorization", "")[7:]
    user = S["tokens"].get(token)
    if not user:
        raise Err(401, "unauthenticated")
    if path == "/activity":
        mine = [pay_view(p) for p in model.payments.values() if p.visibility == "public" or user in (p.frm, p.to)]
        return 200, {"payments": mine[:200], "has_more": len(mine) > 200}
    if path == "/me":
        return 200, me(user, q)
    if path == "/statement":
        return 200, statement(user, q)
    if path == "/payments" and method == "POST":
        key = hdr.get("Idempotency-Key")
        rec = S["keys"].get((user, path, key))
        if rec:
            return 200, rec[1]
        to = S["handles"].get(body.get("to_handle"))
        if not to:
            raise Err(404, "not_found")
        amount = body["amount"]
        if model.me(user, None, None, now())["available"] < amount:
            raise Err(409, "insufficient_funds")
        pid = f"p_{next(S['ids'])}"
        model.add_payment(pid, user, to, amount, now(), visibility=body.get("visibility", "public"))
        out = pay_view(model.payments[pid])
        S["keys"][(user, path, key)] = (body, out)
        return 201, out
    m = None
    import re
    m = re.fullmatch(r"/payments/([^/]+)/corrections", path)
    if m and method == "POST":
        key = hdr.get("Idempotency-Key")
        rec = S["keys"].get((user, path, key))
        if rec:
            if rec[0] != body:
                raise Err(409, "idempotency_key_reuse")
            if BUG == "replay_latest":
                pay = model.payments[m[1]]
                r = pay.revs[-1]
                return 200, {"payment_id": pay.id, "revision": r.n, "amount": r.amount, "effective_at": S.get("raw", {}).get((pay.id, r.n), iso(r.effective_at)), "recorded_at": iso(r.recorded_at), "reason": r.reason}
            return 200, rec[1]
        pay, eff = check_correction(m[1], user, body)
        rec_at = max(now(), pay.revs[-1].recorded_at + timedelta(microseconds=1))
        n = len(pay.revs) + 1
        model.add_revision(pay.id, n, body["amount"], eff, rec_at, body["reason"])
        S.setdefault("raw", {})[(pay.id, n)] = body["effective_at"]
        out = {"payment_id": pay.id, "revision": n, "amount": body["amount"], "effective_at": body["effective_at"], "recorded_at": iso(rec_at), "reason": body["reason"]}
        if BUG == "opening_moves":
            shift = pay.revs[-2].amount - body["amount"]
            model.opening[pay.frm] = model.opening.get(pay.frm, 0) + shift
            model.opening[pay.to] = model.opening.get(pay.to, 0) - shift
        S["keys"][(user, path, key)] = (body, out)
        return 201, out
    m = re.fullmatch(r"/payments/([^/]+)/revisions", path)
    if m:
        pay = model.payments.get(m[1])
        if pay is None or user not in (pay.frm, pay.to):
            raise Err(404, "not_found")
        return 200, {"revisions": [{"revision": r.n, "amount": r.amount, "effective_at": S.get("raw", {}).get((pay.id, r.n), iso(r.effective_at)), "recorded_at": iso(r.recorded_at), "reason": r.reason} for r in pay.revs]}
    if path == "/authorizations" and method == "POST":
        to = S["handles"].get(body.get("to_handle"))
        if not to:
            raise Err(404, "not_found")
        if model.me(user, None, None, now())["available"] < body["amount"]:
            raise Err(409, "insufficient_funds")
        aid = f"a_{next(S['ids'])}"
        t = now()
        model.add_auth(aid, user, to, body["amount"], t, t + timedelta(seconds=S["ttl"]))
        return 201, auth_view(model.auths[aid])
    if path == "/authorizations":
        mine = [a for a in model.auths.values() if user in (a.frm, a.to)]
        return 200, {"authorizations": [auth_view(a) for a in mine], "has_more": False}
    m = re.fullmatch(r"/authorizations/([^/]+)/(capture|void)", path)
    if m:
        a = model.auths.get(m[1])
        if a is None:
            raise Err(404, "not_found")
        view = auth_view(a)
        if m[2] == "void":
            if user != a.frm:
                raise Err(403, "forbidden")
            if view["status"] == "open":
                a.close = ("voided", now())
            elif view["status"] != "voided":
                raise Err(409, "authorization_not_open")
            return 200, auth_view(a)
        if user != a.to:
            raise Err(403, "forbidden")
        if view["status"] == "expired":
            raise Err(409, "authorization_expired")
        if view["status"] != "open":
            raise Err(409, "authorization_not_open")
        done = sum(model.payments[p].revs[0].amount for p in a.captures)
        amount = body.get("amount", a.amount - done)
        if amount > a.amount - done:
            raise Err(422, "capture_exceeds_authorization")
        pid = f"p_{next(S['ids'])}"
        t = now()
        model.add_payment(pid, a.frm, a.to, amount, t, kind="capture")
        model.add_capture(a.id, pid)
        if body.get("final", True) or amount == a.amount - done:
            a.close = ("captured", t)
        return 201, pay_view(model.payments[pid])
    raise Err(404, "not_found")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do(self, method):
        u = urlparse(self.path)
        q = parse_qs(u.query, keep_blank_values=True)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw) if raw else None
            with LOCK:
                status, resp = handle(method, u.path, q, body, self.headers)
        except Err as e:
            status, resp = e.status, {"error": {"code": e.code, "message": e.code}}
        except Exception as e:  # noqa: BLE001
            status, resp = 500, {"error": {"code": "internal", "message": repr(e)}}
        data = b"" if resp is None else json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = lambda s: s.do("GET")      # noqa: E731
    do_POST = lambda s: s.do("POST")    # noqa: E731


class Srv(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256


if __name__ == "__main__":
    Srv(("127.0.0.1", int(os.environ.get("PORT", 18390))), H).serve_forever()
