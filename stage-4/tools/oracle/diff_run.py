#!/usr/bin/env python3
"""Differential and stress tool for Pocketful stage 3 money history.

    TARGET_URL=http://127.0.0.1:18300 python stage-3/tools/oracle/diff_run.py [--ops 120] [--seed 1] [--concurrent 8] [--keep-going]

Drives random operations against the real service and, in lockstep, against the independent reference
model (model.py, written from the specification and the analyst's decisions D-41..D-60). After every
step it queries a grid of /me (as_of, known_at) and /statement (from, to, known_at, limit, offset) views
around every recorded instant (exact and +-1 microsecond / +-1 second) and diffs them with the model;
snapshot tokens taken early must page identically later; a 50-way concurrent phase checks that views
frozen in the past never move while writes land. `--protocol` (default on; `--no-protocol` for stand-ins)
adds the shape and validation checks that need no model: key sets, instant grammar, reset validation,
correction field errors, feed unchanged by corrections, snapshot 404 after reset.
Exit 0 only when nothing diverged. The first divergence prints a minimal repro.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import NEG, POS, UTC, Model, parse  # noqa: E402

PASSWORD = "correct horse"
USERS = 6
ENDING = 50000
BALANCES = [50000, 50000, 50000, 2000, 500, 400]   # low wallets make funds and history limits bite
TTL = 12
FAR_PAST = "1970-01-01T00:00:00+00:00"
FAR_FUTURE = "2100-01-01T00:00:00+00:00"
MICRO = timedelta(microseconds=1)
PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount", "currency", "note", "visibility",
                "request_id", "settlement_id", "authorization_id", "created_at"}
ME_KEYS = {"user_id", "display_name", "handle", "balance", "total", "available", "held", "currency", "minor_units"}


def fmt(t):
    """Whole seconds, +00:00 (what a client typing a time would send)."""
    return t.astimezone(UTC).isoformat(timespec="seconds")


def fmtus(t):
    """Exact microseconds, +00:00 (needed for boundary tests at the clock's own resolution)."""
    return t.astimezone(UTC).isoformat(timespec="microseconds")


class Divergence(Exception):
    pass


class Run:
    def __init__(self, base, seed, keep_going=False):
        self.base = base.rstrip("/")
        self.rng = random.Random(seed)
        self.seed = seed
        self.http = httpx.Client(base_url=self.base, timeout=15, limits=httpx.Limits(max_connections=80))
        self.log = []
        self.findings = []
        self.keep_going = keep_going
        self.skew = timedelta(0)
        self.queries = 0
        self.skip = set()
        self.protocol = True
        self.seed_closed = True
        self.last_instant = NEG
        self.keys = 0
        self.last_span = (datetime.now(UTC), datetime.now(UTC))
        self.skew_samples = []
        self.outcomes = {}
        self.closed_expect = {}
        self.ttl = TTL
        self.reset_instant = None
        self.old_receipts = []
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing
    def call(self, method, path, token=None, body=None, key=None, params=None, timeout=15, raw_query=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        url = path + ("?" + raw_query if raw_query else "")
        sent = datetime.now(UTC)
        r = self.http.request(method, url, headers=headers, json=body, params=params, timeout=timeout)
        self.last_span = (sent, datetime.now(UTC))
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data

    def now(self):
        return datetime.now(UTC) + self.skew

    def note(self, what):
        self.log.append(f"{self.now().strftime('%H:%M:%S.%f')[:-3]} {what}")

    def diverge(self, title, detail):
        text = f"DIVERGENCE: {title}\n{detail}\n-- operations so far (last 25) --\n" + "\n".join(self.log[-25:])
        self.findings.append(text)
        if not self.keep_going:
            raise Divergence(text)

    def expect(self, cond, title, detail=""):
        if not cond:
            self.diverge(title, detail)
        return bool(cond)

    def see(self, text, what):
        """D-41: every server-assigned instant is unique and strictly increases in commit order."""
        t = parse(text)
        with self.lock:
            ok = t > self.last_instant
            previous = self.last_instant
            self.last_instant = max(self.last_instant, t)
        self.expect(ok, "server instants must be unique and strictly increasing (D-41)", f"{what}: {text} is not after {previous.isoformat() if previous != NEG else 'start'}")
        return t

    def key(self):
        with self.lock:
            self.keys += 1
            return f"d{self.seed}-{self.keys}"

    # ------------------------------------------------------------------ setup
    def fixture(self):
        rng = self.rng
        start = self.now().replace(microsecond=0)
        users = [{"id": f"u_{i}", "email": f"u{i}@example.com", "password": PASSWORD, "display_name": f"U{i}",
                  "handle": f"u{i}", "balance": BALANCES[i]} for i in range(USERS)]
        seeded = []
        for k in range(8):
            frm, to = rng.sample(range(USERS), 2)
            offset = rng.choice([0, 2, -5])
            when = (start - timedelta(days=3) + timedelta(hours=k * 5)).astimezone(timezone(timedelta(hours=offset)))
            seeded.append({"id": f"p_seed{k}", "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": rng.randint(1, 100),
                           "note": "seed", "visibility": rng.choice(["public", "private"]), "created_at": when.isoformat(timespec="seconds")})
        for k in range(8, 10):     # created_at omitted: reset time (D-44); public so the feed shows it
            frm, to = rng.sample(range(USERS), 2)
            seeded.append({"id": f"p_seed{k}", "from_user_id": f"u_{frm}", "to_user_id": f"u_{to}", "amount": rng.randint(1, 100),
                           "note": "seed", "visibility": "public"})
        auth = {"id": "a_seed", "from_user_id": "u_1", "to_user_id": "u_2", "amount": 1000, "note": "seeded hold", "visibility": "public",
                "status": "open", "created_at": fmt(start - timedelta(hours=2)), "expires_at": fmt(start + timedelta(hours=3))}
        auths = [auth]
        self.closed_expect = {}
        if self.seed_closed and self.protocol:       # D-51: seeded closed holds hold nothing; closed_at has fixed fallbacks
            auths += [
                {"id": "a_exp", "from_user_id": "u_1", "to_user_id": "u_2", "amount": 300, "note": "seed", "visibility": "public", "status": "expired",
                 "expires_at": fmt(start - timedelta(hours=5))},
                {"id": "a_void", "from_user_id": "u_2", "to_user_id": "u_3", "amount": 200, "note": "seed", "visibility": "public", "status": "voided",
                 "created_at": fmt(start - timedelta(hours=4)), "closed_at": fmt(start - timedelta(hours=3)), "expires_at": fmt(start - timedelta(hours=2))},
                {"id": "a_cap", "from_user_id": "u_3", "to_user_id": "u_4", "amount": 100, "note": "seed", "visibility": "public", "status": "captured",
                 "captured_amount": 100, "created_at": fmt(start - timedelta(hours=2)), "expires_at": fmt(start - timedelta(minutes=90))},
                {"id": "a_void2", "from_user_id": "u_4", "to_user_id": "u_1", "amount": 50, "note": "seed", "visibility": "public", "status": "voided",
                 "expires_at": fmt(start - timedelta(hours=2))},
            ]
            self.closed_expect = {"a_exp": ("expired", "expires_at", "u_1"), "a_void": ("voided", fmt(start - timedelta(hours=3)), "u_2"),
                                  "a_cap": ("captured", fmt(start - timedelta(hours=2)), "u_3"), "a_void2": ("voided", "R", "u_4")}
        return {"currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": TTL, "users": users, "payments": seeded,
                "requests": [], "authorizations": auths, "settlement_operator_ids": ["u_0"]}, seeded, auth

    def setup(self):
        fixture, seeded, auth = self.fixture()
        status, resp = self.call("POST", "/_test/reset", body=fixture, timeout=20)
        if status != 204:
            raise SystemExit(f"reset returned {status} {resp}")
        self.users = [f"u_{i}" for i in range(USERS)]
        self.handles = {f"u_{i}": f"u{i}" for i in range(USERS)}
        self.tokens = {}
        for i in range(USERS):
            status, body = self.call("POST", "/auth/login", body={"email": f"u{i}@example.com", "password": PASSWORD})
            self.tokens[f"u_{i}"] = body["token"]
        self.seeded_total = sum(BALANCES)
        # seeded payments without created_at took the reset time: read it back from the feed (they are public)
        status, feed = self.call("GET", "/activity", self.tokens["u_0"], params={"limit": 200})
        by_id = {p["payment_id"]: p for p in feed["payments"]}
        rows = []
        for p in seeded:
            if "created_at" in p:
                shown = by_id.get(p["id"])
                if shown and self.protocol:
                    self.expect(shown["created_at"] == p["created_at"], "a seeded created_at must be kept exactly as supplied (D-44)", f"{p['id']}: sent {p['created_at']} got {shown['created_at']}")
                created = parse(p["created_at"])
            else:
                self.expect(p["id"] in by_id, "a seeded public payment must appear in the feed", p["id"])
                created = parse(by_id[p["id"]]["created_at"])
            rows.append((p["id"], p["from_user_id"], p["to_user_id"], p["amount"], created, p["visibility"]))
        omitted = [parse(by_id[p["id"]]["created_at"]) for p in seeded if "created_at" not in p]
        self.expect(all(t <= self.now() for t in omitted), "omitted seeded created_at must be the reset time, not later than now", str(omitted))
        self.reset_instant = min(omitted) if omitted else None
        self.expect(len(set(omitted)) <= 1, "every omitted seeded created_at is the one reset instant (D-44)", str(omitted))
        self.model = Model.from_seed({u["id"]: u["balance"] for u in fixture["users"]}, rows)
        self.model.add_auth(auth["id"], auth["from_user_id"], auth["to_user_id"], auth["amount"], parse(auth["created_at"]), parse(auth["expires_at"]))
        self.auths = [auth["id"]]
        self.snapshots = []
        self.keys = 0
        self.payment_keys = None
        self.note(f"reset: {USERS} users, {len(seeded)} seeded payments (2 without created_at), 1 seeded hold, ttl {TTL}s, seed {self.seed}")

    # ------------------------------------------------------------------ operations (each records into the model)
    def op_payment(self):
        frm, to = self.rng.sample(self.users, 2)
        amount = self.rng.choice([1, 5, 20, 100, 400])
        body = {"to_handle": self.handles[to], "amount": amount, "note": "diff", "visibility": self.rng.choice(["public", "private"])}
        status, resp = self.call("POST", "/payments", self.tokens[frm], body, self.key())
        self.note(f"POST /payments {frm}->{to} {amount} => {status}")
        if status == 201:
            self.learn_skew(resp["created_at"])
            if self.payment_keys is None:
                self.payment_keys = set(resp)
                if self.protocol:
                    self.expect(self.payment_keys == PAYMENT_KEYS, "payment object key set (stage 2: 13 keys, original receipt unchanged)", f"{sorted(self.payment_keys ^ PAYMENT_KEYS)}")
            created = self.see(resp["created_at"], "payment created_at")
            self.model.add_payment(resp["payment_id"], frm, to, amount, created, visibility=body["visibility"])
        else:
            self.expect(status == 409 and resp["error"]["code"] == "insufficient_funds", "payment refused unexpectedly", f"{status} {resp}")

    def op_settlement(self):
        picks = self.rng.sample(self.users, 3)
        transfers = [{"from_handle": self.handles[picks[0]], "to_handle": self.handles[picks[1]], "amount": self.rng.choice([1, 10, 50])},
                     {"from_handle": self.handles[picks[1]], "to_handle": self.handles[picks[2]], "amount": self.rng.choice([1, 10, 50])}]
        status, resp = self.call("POST", "/settlements", self.tokens["u_0"], {"transfers": transfers}, self.key())
        self.note(f"POST /settlements {[(t['from_handle'], t['to_handle'], t['amount']) for t in transfers]} => {status}")
        if status == 201:
            committed = self.see(resp["committed_at"], "settlement committed_at")
            for member, t in zip(resp["payments"], transfers):
                frm = next(u for u, h in self.handles.items() if h == t["from_handle"])
                to = next(u for u, h in self.handles.items() if h == t["to_handle"])
                self.expect(parse(member["created_at"]) == committed, "settlement member created_at != committed_at", json.dumps(member))
                self.model.add_payment(member["payment_id"], frm, to, t["amount"], committed, kind="settlement", visibility=member["visibility"])

    def op_request_pay(self):
        payer, requester = self.rng.sample(self.users, 2)
        status, rq = self.call("POST", "/requests", self.tokens[requester], {"payer_handle": self.handles[payer], "amount": 25, "note": "diff"}, self.key())
        if status != 201:
            return
        status, resp = self.call("POST", f"/requests/{rq['request_id']}/pay", self.tokens[payer], {"visibility": "public"}, self.key())
        self.note(f"request+pay {payer}->{requester} 25 => {status}")
        if status == 201:
            self.model.add_payment(resp["payment_id"], payer, requester, 25, self.see(resp["created_at"], "request payment created_at"))

    def op_authorize(self):
        frm, to = self.rng.sample(self.users, 2)
        amount = self.rng.choice([50, 200, 800])
        status, resp = self.call("POST", "/authorizations", self.tokens[frm], {"to_handle": self.handles[to], "amount": amount, "note": "hold"}, self.key())
        self.note(f"POST /authorizations {frm}->{to} {amount} => {status}")
        if status == 201:
            created = self.see(resp["created_at"], "authorization created_at")
            self.model.add_auth(resp["authorization_id"], frm, to, amount, created, parse(resp["expires_at"]))
            self.auths.append(resp["authorization_id"])
            self.expect(resp.get("closed_at", "missing") is None, "a new authorization must expose closed_at: null", json.dumps(resp))
            self.expect(parse(resp["expires_at"]) == created + timedelta(seconds=self.ttl), "expires_at must be created_at + ttl (microseconds kept, D-41)", json.dumps(resp))
        else:
            self.expect(status == 409, "authorize refused unexpectedly", f"{status} {resp}")

    def sync_auths(self, users=None):
        """Read every authorization back and teach the model about closes; check closed_at (D-51)."""
        for user in users or self.users:
            status, resp = self.call("GET", "/authorizations", self.tokens[user], params={"limit": 200})
            if status != 200:
                continue
            for a in resp["authorizations"]:
                auth = self.model.auths.get(a["authorization_id"])
                if auth is None:
                    continue
                st, closed = a["status"], a.get("closed_at", "missing")
                if st == "open":
                    self.expect(closed is None, "open authorization must have closed_at null", json.dumps(a))
                elif st == "expired":
                    self.expect(closed not in (None, "missing") and parse(closed) == auth.expires_at, "expired authorization closed_at must be its expires_at", json.dumps(a))
                elif st in ("captured", "voided"):
                    self.expect(closed not in (None, "missing"), "closed authorization must expose closed_at", json.dumps(a))
                    if auth.close is None:
                        self.model.close_auth(a["authorization_id"], st, parse(closed))
                    else:
                        self.expect(auth.close[1] == parse(closed), "closed_at changed", json.dumps(a))
                    if st == "captured" and auth.captures:
                        last = self.model.payments[auth.captures[-1]].created_at
                        self.expect(parse(closed) == last, "a captured authorization closes at its closing capture's instant (D-51)", json.dumps(a))

    def open_auths(self):
        return [a for a in self.auths if self.model.auths[a].close is None and self.model.auths[a].expires_at > self.now() + timedelta(seconds=1)]

    def op_capture(self):
        open_ones = self.open_auths()
        if not open_ones:
            return
        aid = self.rng.choice(open_ones)
        auth = self.model.auths[aid]
        remaining = auth.amount - sum(self.model.payments[p].revs[0].amount for p in auth.captures)
        if remaining <= 0:
            return
        amount = self.rng.choice([1, min(remaining, 30), remaining])
        body = {"amount": amount}
        if self.rng.random() < 0.5:
            body["final"] = False
        status, resp = self.call("POST", f"/authorizations/{aid}/capture", self.tokens[auth.to], body, self.key())
        self.note(f"POST capture {aid} {body} => {status}")
        if status == 201:
            self.model.add_payment(resp["payment_id"], auth.frm, auth.to, amount, self.see(resp["created_at"], "capture created_at"), kind="capture")
            self.model.add_capture(aid, resp["payment_id"])
        else:
            code = (resp or {}).get("error", {}).get("code")
            self.expect(code in ("authorization_expired", "authorization_not_open"), "capture refused unexpectedly", f"{status} {resp}")
        self.sync_auths([auth.frm])

    def op_void(self):
        open_ones = self.open_auths()
        if not open_ones:
            return
        aid = self.rng.choice(open_ones)
        auth = self.model.auths[aid]
        status, resp = self.call("POST", f"/authorizations/{aid}/void", self.tokens[auth.frm])
        self.note(f"POST void {aid} => {status}")
        if status == 200 and resp["status"] == "voided":
            self.see(resp["closed_at"], "void closed_at")
            self.model.close_auth(aid, "voided", parse(resp["closed_at"]))
        self.sync_auths([auth.frm])

    def pick_instant(self, now, pays):
        choice = self.rng.random()
        floor = min(p.current().effective_at for p in pays)
        if choice < 0.2:
            effective = self.rng.choice(pays).created_at
        elif choice < 0.45:
            effective = self.rng.choice([p.current().effective_at for p in pays]) + self.rng.choice([-MICRO, timedelta(0), timedelta(0), MICRO])
        else:
            span = max(int((now - floor).total_seconds()) - 2, 1)
            effective = floor + timedelta(seconds=self.rng.randrange(span), microseconds=self.rng.choice([0, 0, 500000, 123456]))
        return min(effective, now - timedelta(seconds=2))

    def op_correction(self):
        pays = list(self.model.payments.values())
        pay = self.rng.choice(pays)
        actor = pay.frm if self.rng.random() < 0.85 else self.rng.choice([u for u in self.users if u != pay.frm])
        expected = len(pay.revs) if self.rng.random() < 0.8 else (len(pay.revs) + self.rng.choice([-1, 1]) or 1)
        cur = pay.current().amount
        amount = self.rng.choice([0, max(cur - 1, 0), cur, cur + 1, cur + 30, 3 * cur + 7, 1])
        now = self.now()
        effective = self.pick_instant(now, pays)
        text = fmtus(effective) if self.rng.random() < 0.7 else fmt(effective)
        self.do_correction(pay, actor, expected, amount, text)

    def do_correction(self, pay, actor, expected, amount, text):
        now = self.now()
        effective = parse(text)
        body = {"expected_revision": expected, "amount": amount, "effective_at": text, "reason": "diff correction"}
        want = self.model.correction_result(pay.id, actor, expected, amount, effective, now)
        key = self.key()
        status, resp = self.call("POST", f"/payments/{pay.id}/corrections", self.tokens[actor], body, key)
        code = "ok" if status == 201 else (str(status) if status in (403, 404) else ((resp or {}).get("error") or {}).get("code") if isinstance(resp, dict) else None)
        self.note(f"POST correction {pay.id} by {actor} {body} => {status} {code} (model: {want})")
        self.outcomes[code] = self.outcomes.get(code, 0) + 1
        if code != want:
            self.diverge("correction outcome (D-46 order)", f"payment {pay.id} actor {actor} body {json.dumps(body)}\nmodel says {want}, service answered {status} {resp}")
            return
        if status == 201:
            self.expect(resp["revision"] == len(pay.revs) + 1 and resp["amount"] == amount and resp["effective_at"] == text
                        and resp["payment_id"] == pay.id and resp["reason"] == body["reason"] and set(resp) == {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"},
                        "correction receipt must be {payment_id, revision, amount, effective_at (as supplied), recorded_at, reason}", json.dumps(resp))
            self.see(resp["recorded_at"], "correction recorded_at")
            self.add_rev(pay.id, resp, amount, effective, body["reason"])
            self.check_replay(pay.id, actor, key, body, resp)
            self.check_revisions(pay.id)
            self.old_receipts.append((pay.id, actor, key, body, resp))
        elif code == "stale_revision" and self.rng.random() < 0.5:      # D-57: a refusal claims no key
            body2 = dict(body, expected_revision=len(pay.revs))
            want2 = self.model.correction_result(pay.id, actor, body2["expected_revision"], amount, effective, now)
            status2, resp2 = self.call("POST", f"/payments/{pay.id}/corrections", self.tokens[actor], body2, key)
            code2 = "ok" if status2 == 201 else ((resp2 or {}).get("error") or {}).get("code")
            self.expect(code2 == want2, "a refused correction must leave its idempotency key free (D-57)", f"same key, expected_revision {body2['expected_revision']}: model {want2}, got {status2} {resp2}")
            if status2 == 201:
                self.see(resp2["recorded_at"], "correction recorded_at")
                self.add_rev(pay.id, resp2, amount, effective, body["reason"])
                self.old_receipts.append((pay.id, actor, key, body2, resp2))

    def check_old_replays(self):
        """A successful replay returns the ORIGINAL revision with 200 even after newer revisions exist."""
        for pid, actor, key, body, original in self.rng.sample(self.old_receipts, min(3, len(self.old_receipts))):
            status, again = self.call("POST", f"/payments/{pid}/corrections", self.tokens[actor], body, key)
            self.expect(status == 200 and again == original, "replay after newer revisions must still return the original revision (spec: Successful replay)",
                        f"{pid}: {status} {again} vs original {original} (now at revision {len(self.model.payments[pid].revs)})")

    def scenario_overdraft(self):
        """Deterministic: a receiver spends money that a later correction would remove (historical_overdraft)."""
        a, b, d = "u_3", "u_5", "u_0"
        status, me = self.call("GET", "/me", self.tokens[b])
        tb = me["available"]
        x = 400
        steps = [(a, b, x), (b, "u_4", tb + x - 10), (d, b, 500)]
        ids = []
        for frm, to, amount in steps:
            status, resp = self.call("POST", "/payments", self.tokens[frm], {"to_handle": self.handles[to], "amount": amount, "note": "scenario"}, self.key())
            self.note(f"scenario payment {frm}->{to} {amount} => {status}")
            if status != 201:
                return
            self.model.add_payment(resp["payment_id"], frm, to, amount, self.see(resp["created_at"], "scenario payment"))
            ids.append(resp["payment_id"])
        time.sleep(2.1)
        pay = self.model.payments[ids[0]]
        self.do_correction(pay, a, 1, 0, fmtus(pay.created_at))          # removes b's money before b spent it: historical_overdraft
        self.do_correction(pay, a, 1, 50, fmtus(pay.created_at))         # a smaller reduction that b can still cover

    def add_rev(self, pid, resp, amount, effective, reason):
        pay = self.model.payments[pid]
        recorded = parse(resp["recorded_at"])
        self.expect(resp["revision"] == len(pay.revs) + 1, "revision numbers must be consecutive", f"{pid}: got {resp['revision']} after {len(pay.revs)}")
        self.expect(recorded > pay.revs[-1].recorded_at, "recorded times of one payment must strictly increase",
                    f"{pid}: revision {resp['revision']} recorded {resp['recorded_at']} not after {fmtus(pay.revs[-1].recorded_at)}")
        self.model.add_revision(pid, resp["revision"], amount, effective, recorded, reason)

    def check_replay(self, pid, actor, key, body, original):
        status, again = self.call("POST", f"/payments/{pid}/corrections", self.tokens[actor], body, key)
        self.expect(status == 200 and again == original, "correction replay must return 200 and the original revision", f"{status} {again} vs {original}")
        status, other = self.call("POST", f"/payments/{pid}/corrections", self.tokens[actor], dict(body, amount=body["amount"] + 1), key)
        self.expect(status == 409 and other["error"]["code"] == "idempotency_key_reuse", "same key, different body must be 409 idempotency_key_reuse", f"{status} {other}")

    def check_revisions(self, pid):
        pay = self.model.payments[pid]
        status, resp = self.call("GET", f"/payments/{pid}/revisions", self.tokens[pay.frm])
        self.expect(status == 200 and set(resp) == {"revisions"}, "revisions must be readable by the sender as {revisions: [...]}", f"{status} {resp}")
        got = [(r["revision"], r["amount"], parse(r["effective_at"]), parse(r["recorded_at"]), r["reason"]) for r in resp["revisions"]]
        want = [(r.n, r.amount, r.effective_at, r.recorded_at, r.reason) for r in pay.revs]
        self.expect(got == want, "revision history differs", f"{pid}: got {got}\nwant {want}")
        self.expect(resp["revisions"][0]["reason"] == "" and resp["revisions"][0]["revision"] == 1, "revision 1 has reason ''", json.dumps(resp["revisions"][0]))
        status, _ = self.call("GET", f"/payments/{pid}/revisions", self.tokens[pay.to])
        self.expect(status == 200, "the receiver may read the revisions", str(status))
        outsider = next(u for u in self.users if u not in (pay.frm, pay.to))
        status, resp = self.call("GET", f"/payments/{pid}/revisions", self.tokens[outsider])
        self.expect(status == 404, "a third party must get 404 on revisions", f"{status} {resp}")
        status, resp = self.call("GET", f"/payments/{pid}/revisions")
        self.expect(status == 401, "no token must get 401 on revisions", f"{status}")

    # ------------------------------------------------------------------ view checks
    def learn_skew(self, created_at):
        """Server clock minus client clock, from the instant a payment was created vs the midpoint of its request."""
        sent, received = self.last_span
        delta = parse(created_at) - (sent + (received - sent) / 2)
        if abs(delta) < timedelta(seconds=3):
            self.skew_samples = (self.skew_samples + [delta])[-15:]
            ordered = sorted(self.skew_samples)
            self.skew = ordered[len(ordered) // 2]

    def read_instants(self, span):
        """The model cannot see the read instant N; N lies inside the request's span (server clock). Candidates: the span ends
        and every recorded instant inside it (the answer only changes at those instants)."""
        sent, received = span
        slack = timedelta(milliseconds=25) if self.skew_samples else timedelta(seconds=1)
        lo, hi = sent + self.skew - slack, received + self.skew + slack
        out = {lo, hi}
        m = self.model
        events = []
        for pay in m.payments.values():
            events += [rev.recorded_at for rev in pay.revs]
        for a in m.auths.values():
            events += [a.created_at, a.expires_at] + ([a.close[1]] if a.close else [])
        for e in events:
            if lo - MICRO <= e <= hi + MICRO:
                out.update([e - MICRO, e, e + MICRO])
        return sorted(out)

    def instants(self):
        pool = set()
        m = self.model
        for pay in m.payments.values():
            for rev in pay.revs:
                pool.update([rev.effective_at, rev.recorded_at])
        for a in m.auths.values():
            pool.update([a.created_at, a.expires_at])
            if a.close:
                pool.add(a.close[1])
        pool.add(self.now())
        out = set()
        for t in pool:
            out.update([t, t - MICRO, t + MICRO, t - timedelta(seconds=1), t + timedelta(seconds=1)])
        return sorted(out) + [parse(FAR_PAST), parse(FAR_FUTURE)]

    def render(self, instant):
        form = self.rng.random()
        if form < 0.35:
            return fmtus(instant)
        if form < 0.55:
            return fmtus(instant).replace("+00:00", "Z")
        if form < 0.75:
            return instant.astimezone(timezone(timedelta(hours=2))).isoformat(timespec="microseconds")
        if form < 0.9:
            return fmtus(instant).replace("+00:00", "z").replace("T", "t")
        trimmed = fmtus(instant)[:-6].rstrip("0").rstrip(".")      # 12:00:00.7 or 12:00:00 forms
        return trimmed + "+00:00"

    def me_view(self, user, as_of_text, known_text):
        params = {}
        if as_of_text:
            params["as_of"] = as_of_text
        if known_text:
            params["known_at"] = known_text
        status, resp = self.call("GET", "/me", self.tokens[user], params=params)
        span = self.last_span
        self.queries += 1
        if not self.expect(status == 200, "GET /me failed", f"{params} => {status} {resp}"):
            return None
        as_of = parse(as_of_text) if as_of_text else None
        known = parse(known_text) if known_text else None
        got = {k: resp.get(k) for k in ("balance", "total", "available", "held")}
        tried = []
        for now in self.read_instants(span):
            want = self.model.me(user, as_of, known, now)
            tried.append(want)
            if want == got:
                break
        else:
            self.diverge("GET /me view", f"user {user} params {params}\nmodel   {tried[len(tried) // 2]}\nservice {got}\n"
                         f"repro: curl -G -H 'Authorization: Bearer <{user} token>' {self.base}/me " + " ".join(f"--data-urlencode '{k}={v}'" for k, v in params.items()))
        if as_of_text:
            self.expect(resp.get("as_of") == as_of_text, "as_of must be echoed exactly (D-43)", f"sent {as_of_text!r} got {resp.get('as_of')!r}")
        if known_text:
            self.expect(resp.get("known_at") == known_text, "known_at must be echoed exactly (D-43)", f"sent {known_text!r} got {resp.get('known_at')!r}")
        if self.protocol and not params:
            self.expect(set(resp) == ME_KEYS, "GET /me without temporal parameters keeps the stage 2 key set (D-43)", f"{sorted(set(resp) ^ ME_KEYS)}")
        self.expect(resp["balance"] == resp["total"] and resp["available"] == resp["total"] - resp["held"] and resp["held"] >= 0 and resp["available"] >= 0,
                    "money fields must agree in one view", json.dumps(resp))
        return resp

    @staticmethod
    def shape(resp):
        entries = []
        for e in resp["entries"]:
            p = e["payment"]
            entries.append((p["payment_id"], e["revision"], p["amount"], e["delta"], e["balance_after"], parse(e["effective_at"]), parse(e["recorded_at"])))
        return {"opening_balance": resp["opening_balance"], "closing_balance": resp["closing_balance"], "entries": entries, "has_more": resp["has_more"]}

    @staticmethod
    def entry_tuple(e):
        return (e["id"], e["revision"], e["amount"], e["delta"], e["balance_after"], e["effective_at"], e["recorded_at"])

    def want_page(self, full, limit, offset):
        return {"opening_balance": full["opening_balance"], "closing_balance": full["closing_balance"],
                "entries": [self.entry_tuple(e) for e in full["entries"][offset:offset + limit]], "has_more": offset + limit < len(full["entries"])}

    def stmt_view(self, user, frm_t, to_t, known_t, limit, offset, want_snapshot=False):
        params = {}
        for name, value in (("from", frm_t), ("to", to_t), ("known_at", known_t)):
            if value:
                params[name] = value
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        status, resp = self.call("GET", "/statement", self.tokens[user], params=params)
        span = self.last_span
        self.queries += 1
        if not self.expect(status == 200, "GET /statement failed", f"{params} => {status} {resp}"):
            return None
        frm, to, known = (parse(x) if x else None for x in (frm_t, to_t, known_t))
        nows = self.read_instants(span) if to is None else [span[0] + self.skew]
        shape = self.shape(resp)
        lim = 50 if limit is None else limit
        off = 0 if offset is None else offset
        matched = None
        for now in nows:
            full = self.model.statement(user, frm, to, known, now)
            if self.want_page(full, lim, off) == shape:
                matched = full
                break
        if matched is None:
            full = self.model.statement(user, frm, to, known, nows[len(nows) // 2])
            self.diverge("GET /statement view", f"user {user} params {params}\nmodel   {json.dumps(self.want_page(full, lim, off), default=str)}\nservice {json.dumps(shape, default=str)}\n"
                         f"repro: curl -G -H 'Authorization: Bearer <{user} token>' {self.base}/statement " + " ".join(f"--data-urlencode '{k}={v}'" for k, v in params.items()))
            return None
        self.expect(matched["opening_balance"] + sum(e["delta"] for e in matched["entries"]) == matched["closing_balance"], "opening + deltas != closing", "")
        if known_t:
            self.expect(resp.get("known_at") == known_t, "statement must echo known_at exactly", f"sent {known_t!r} got {resp.get('known_at')!r}")
        self.expect(isinstance(resp.get("snapshot"), str) and resp["snapshot"], "the first statement response must carry a snapshot token", json.dumps(params))
        if self.protocol:
            want_keys = {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"} | ({"known_at"} if known_t else set())
            self.expect(set(resp) == want_keys, "statement response key set (D-49)", f"{sorted(set(resp) ^ want_keys)}")
            for e in resp["entries"]:
                self.expect(set(e) == {"payment", "delta", "revision", "effective_at", "recorded_at", "balance_after"}, "statement entry key set (D-49)", json.dumps(e))
                self.expect(set(e["payment"]) == PAYMENT_KEYS, "statement payment is the stage 2 payment object (13 keys) with the selected amount", f"{sorted(set(e['payment']) ^ PAYMENT_KEYS)}")
        if want_snapshot and resp.get("snapshot"):
            self.snapshots.append((user, resp["snapshot"], matched, params))
        return resp

    def check_snapshots(self):
        for user, token, frozen, params in self.snapshots:
            lim = self.rng.choice([1, 2, 3, 50])
            off = self.rng.choice([0, 1, 2, 5, 100])
            status, resp = self.call("GET", "/statement", self.tokens[user], params={"snapshot": token, "limit": lim, "offset": off})
            if not self.expect(status == 200, "snapshot paging failed", f"{token} {status} {resp}"):
                continue
            want = self.want_page(frozen, lim, off)
            self.expect(self.shape(resp) == want, "snapshot page changed after later writes (D-50)",
                        f"user {user} first params {params} then limit={lim} offset={off}\nfrozen {json.dumps(want, default=str)}\ngot    {json.dumps(self.shape(resp), default=str)}")
        if self.snapshots:
            user, token, _, _ = self.snapshots[0]
            other = next(u for u in self.users if u != user)
            status, _ = self.call("GET", "/statement", self.tokens[other], params={"snapshot": token})
            self.expect(status == 404, "another user's snapshot token must be 404", str(status))
            status, _ = self.call("GET", "/statement", self.tokens[user], params={"snapshot": "nope-" + token})
            self.expect(status == 404, "an unknown snapshot token must be 404", str(status))
            for extra in ({"from": FAR_PAST}, {"to": FAR_FUTURE}, {"known_at": FAR_PAST}, {"known_at": ""}):
                status, _ = self.call("GET", "/statement", self.tokens[user], params={"snapshot": token, **extra})
                self.expect(status == 422, f"snapshot with {list(extra)[0]} must be 422 (D-50)", str(status))

    def check_bad_instants(self):
        user = self.users[0]
        paths = (("/me", "as_of"), ("/me", "known_at")) if "statement" in self.skip else (("/me", "as_of"), ("/me", "known_at"), ("/statement", "from"), ("/statement", "to"), ("/statement", "known_at"))
        bad = ["2026-09-24T10:00:00", "2026-09-24", "", "yesterday", "2026-13-01T00:00:00+00:00", "2026-02-30T00:00:00Z", "2026-09-24T10:00:60Z",
               "2026-09-24T10:00:00+24:00", "2026-09-24 10:00:00Z", "2026-09-24T10:00:00.1234567890Z", "1700000000", "2026-09-24T10:00:00 +00:00"]
        for value in bad:
            for path, name in paths:
                status, resp = self.call("GET", path, self.tokens[user], params={name: value})
                self.expect(status == 422 and resp["error"]["code"] == "validation_failed", f"{path}?{name}={value!r} must be 422 validation_failed (D-42)", f"{status} {resp}")
        if "statement" in self.skip:
            return
        status, resp = self.call("GET", "/statement", self.tokens[user], params={"from": "2026-09-24T10:00:00Z", "to": "2026-09-24T09:00:00Z"})
        self.expect(status == 422, "from after to must be 422 (D-54)", f"{status} {resp}")
        same = "2026-09-24T10:00:00Z"
        status, resp = self.call("GET", "/statement", self.tokens[user], params={"from": same, "to": same})
        self.expect(status == 200 and resp["entries"] == [] and resp["opening_balance"] == resp["closing_balance"], "from = to is an empty window (D-54)", f"{status} {resp}")

    def check_query_forms(self):
        """D-42: a decoded '+' is repaired; the last repeated parameter wins; unknown parameters are ignored."""
        user = self.users[1]
        t = self.rng.choice(self.instants()[:-2])
        text = fmtus(t)
        status, a = self.call("GET", "/me", self.tokens[user], params={"as_of": text})
        status2, b = self.call("GET", "/me", self.tokens[user], raw_query=f"as_of={text}")          # unencoded '+'
        self.expect(status == 200 and status2 == 200 and all(a[k] == b[k] for k in ("balance", "total", "available", "held")),
                    "an unencoded '+' in a query instant must be read as +HH:MM (D-42)", f"{status}/{status2} {a} {b}")
        status, c = self.call("GET", "/me", self.tokens[user], raw_query=f"as_of={FAR_PAST.replace('+', '%2B')}&as_of={text.replace('+', '%2B')}&unknown=1")
        self.expect(status == 200 and all(a[k] == c[k] for k in ("balance", "total", "available", "held")), "the last repeated as_of wins; unknown parameters are ignored (D-42)", f"{status} {c}")
        status, d = self.call("GET", "/me", self.tokens[user], params={"as_of": text, "known_at": FAR_FUTURE})
        self.expect(status == 200 and all(a[k] == d[k] for k in ("balance", "total", "available", "held")), "a future known_at selects everything recorded so far", f"{status} {d}")

    def grid(self, count=14):
        pool = self.instants()
        users = self.rng.sample(self.users, 3)
        for _ in range(count):
            user = self.rng.choice(users)
            a = self.render(self.rng.choice(pool)) if self.rng.random() < 0.85 else None
            k = self.render(self.rng.choice(pool)) if self.rng.random() < 0.6 else None
            self.me_view(user, a, k)
        for _ in range(0 if "statement" in self.skip else count // 2):
            user = self.rng.choice(users)
            lo, hi = sorted([self.rng.choice(pool), self.rng.choice(pool)])
            f = self.render(lo) if self.rng.random() < 0.6 else None
            t = self.render(hi) if self.rng.random() < 0.75 else None
            if f and t is None and lo > self.now() - timedelta(seconds=1):    # from vs the default `to` (now) would be ambiguous
                f = None
            k = self.render(self.rng.choice(pool)) if self.rng.random() < 0.5 else None
            self.stmt_view(user, f, t, k, self.rng.choice([None, 1, 2, 3, 200]), self.rng.choice([None, 0, 1, 4]), want_snapshot=self.rng.random() < 0.3)
        pool_t = self.rng.choice(pool)
        known = self.rng.choice([None] + pool)
        total = 0
        for u in self.users:
            resp = self.me_view(u, fmtus(pool_t), fmtus(known) if known else None)
            total += resp["total"] if resp else 0
        self.expect(total == self.seeded_total, "sum of wallet totals != seeded total in a historical view",
                    f"as_of={fmtus(pool_t)} known_at={fmtus(known) if known else None}: {total} != {self.seeded_total}")

    def all_nonnegative(self):
        """Every user's total and available are >= 0 at every boundary of the final history (D-53)."""
        m = self.model
        for t in m.boundaries(self.now() + timedelta(seconds=2)) + [NEG]:
            for u in self.users:
                total = m.total(u, t, None)
                self.expect(total >= 0 and total - m.held(u, t, None) >= 0, "historical overdraft slipped through",
                            f"user {u} at {fmtus(t) if t != NEG else 'the beginning'}: total {total}, available {total - m.held(u, t, None)}")

    # ------------------------------------------------------------------ protocol checks (no model needed)
    def check_corrections_validation(self):
        pay = next(p for p in self.model.payments.values() if p.kind == "plain")
        tok = self.tokens[pay.frm]
        good = {"expected_revision": len(pay.revs), "amount": pay.current().amount, "effective_at": fmt(self.now() - timedelta(seconds=30)), "reason": "x"}
        bad = {"missing expected_revision": {k: v for k, v in good.items() if k != "expected_revision"},
               "missing amount": {k: v for k, v in good.items() if k != "amount"},
               "missing effective_at": {k: v for k, v in good.items() if k != "effective_at"},
               "missing reason": {k: v for k, v in good.items() if k != "reason"},
               "null amount": dict(good, amount=None), "string amount": dict(good, amount="5"), "bool amount": dict(good, amount=True),
               "fractional amount": dict(good, amount=1.5), "negative amount": dict(good, amount=-1), "amount over 1e9": dict(good, amount=1000000001),
               "revision 0": dict(good, expected_revision=0), "revision string": dict(good, expected_revision="1"), "revision negative": dict(good, expected_revision=-1),
               "empty reason": dict(good, reason=""), "reason 201 chars": dict(good, reason="x" * 201), "reason number": dict(good, reason=5),
               "naive effective_at": dict(good, effective_at="2026-09-24T10:00:00"), "date effective_at": dict(good, effective_at="2026-09-24"),
               "future effective_at": dict(good, effective_at=fmt(self.now() + timedelta(seconds=30)))}
        for name, body in bad.items():
            for target in (pay.id, "p_does_not_exist"):
                status, resp = self.call("POST", f"/payments/{target}/corrections", tok, body, self.key())
                self.expect(status == 422 and resp["error"]["code"] == "validation_failed", f"correction body defect '{name}' must be 422 validation_failed before 404/403 (D-46)", f"{target}: {status} {resp}")
        status, resp = self.call("POST", f"/payments/{pay.id}/corrections", tok, good)
        self.expect(status == 400 and resp["error"]["code"] == "missing_idempotency_key", "a correction needs an Idempotency-Key", f"{status} {resp}")
        status, resp = self.call("POST", f"/payments/{pay.id}/corrections", None, good, self.key())
        self.expect(status == 401, "a correction without a token is 401", str(status))
        status, resp = self.call("POST", f"/payments/{pay.id}/corrections", tok, None, self.key())
        self.expect(status == 400, "a correction with no JSON object is 400 malformed_request", f"{status} {resp}")

    def check_feed_unchanged(self):
        """D-56: corrections never change /activity: same payments, original amounts, no extra items."""
        for user in self.users[:3]:
            status, feed = self.call("GET", "/activity", self.tokens[user], params={"limit": 200})
            if status != 200:
                continue
            seen = {p["payment_id"]: p for p in feed["payments"]}
            want = {pid for pid, p in self.model.payments.items() if p.visibility == "public" or user in (p.frm, p.to)}
            if feed.get("has_more"):
                continue
            self.expect(set(seen) == want, "the activity feed must list exactly the original payments, no correction records (D-56)", f"{user}: extra {sorted(set(seen) - want)[:5]} missing {sorted(want - set(seen))[:5]}")
            for pid, item in seen.items():
                if pid in self.model.payments:
                    self.expect(item["amount"] == self.model.payments[pid].revs[0].amount, "the feed shows the ORIGINAL amount after corrections (D-56)", f"{pid}: {item['amount']} vs {self.model.payments[pid].revs[0].amount}")

    # ------------------------------------------------------------------ upgrade path (D-52)
    def setup_upgrade(self, data):
        """Adopt an imported stage-1/2 export: users, tokens and the model rebuilt from the export's state (D-52)."""
        state = data["export"]["state"]
        self.users = list(state["users"])
        self.handles = {u: state["users"][u]["handle"] for u in self.users}
        self.tokens = dict(data["tokens"])
        self.model = Model.from_import(state)
        self.seeded_total = sum(u["balance"] for u in state["users"].values())
        self.auths = list(self.model.auths)
        self.snapshots = []
        self.keys = 0
        self.payment_keys = None
        self.upgrade = data
        self.ttl = state.get("settings", {}).get("authorization_ttl_seconds", 600)     # stage-1 exports carry none: the default (D-52)
        instants = [p.created_at for p in self.model.payments.values()] + [a.created_at for a in self.model.auths.values()]
        self.last_instant = max(instants) if instants else NEG
        self.note(f"imported a stage {data['stage']} export: {len(state['users'])} users, {len(self.model.payments)} payments, {len(self.model.auths)} authorizations")

    def check_import(self):
        data, state = self.upgrade, self.upgrade["export"]["state"]
        for u in self.users:
            status, me = self.call("GET", "/me", self.tokens[u])
            if not self.expect(status == 200, "a source token must still authenticate after the import (D-52)", f"{u}: {status} {me}"):
                continue
            src = state["users"][u]
            held = src.get("held", 0)
            self.expect(me["balance"] == src["balance"] and me["total"] == src["balance"] and me["held"] == held and me["available"] == src["balance"] - held,
                        "imported balances, held and available must equal the export's", f"{u}: {me} vs balance {src['balance']} held {held}")
        replayed = 0
        for w in data["writes"]:
            if w["user"] not in self.tokens:
                continue
            status, resp = self.call("POST", w["path"], self.tokens[w["user"]], w["body"], w["key"])
            replayed += 1
            self.expect(status == 200 and resp == w["response"], "an imported idempotent receipt must replay 200 with the original body (D-52)",
                        f"{w['path']} key {w['key']}: {status} {json.dumps(resp)[:200]} vs {json.dumps(w['response'])[:200]}")
        self.note(f"replayed {replayed} imported idempotent writes")
        self.sync_auths()

    def check_linked(self):
        """Imported settlement members and captures are immutable; an ordinary imported payment is correctable."""
        linked = [p for p in self.model.payments.values() if p.kind in ("settlement", "capture")]
        plain = [p for p in self.model.payments.values() if p.kind == "plain"]
        for pay in self.rng.sample(linked, min(8, len(linked))):
            self.do_correction(pay, pay.frm, 1, max(pay.current().amount - 1, 0), fmt(self.now() - timedelta(seconds=30)))
        for pay in self.rng.sample(plain, min(3, len(plain))):
            self.do_correction(pay, pay.frm, 1, max(pay.current().amount - 1, 0), fmt(self.now() - timedelta(seconds=30)))
        self.note(f"checked {min(8, len(linked))} linked and {min(3, len(plain))} ordinary imported payments")

    def check_seeded_closed(self):
        """D-51: seeded closed holds hold nothing (the /me grid covers that); closed_at = supplied closed_at, else expires_at
        (expired), else supplied created_at, else the reset instant."""
        for aid, (status, closed, user) in self.closed_expect.items():
            code, resp = self.call("GET", "/authorizations", self.tokens[user], params={"limit": 200})
            item = next((a for a in (resp or {}).get("authorizations", []) if a["authorization_id"] == aid), None)
            if not self.expect(item is not None, "a seeded closed authorization must be listed", f"{aid} for {user}: {code}"):
                continue
            self.expect(item["status"] == status, "a seeded closed authorization keeps its status", f"{aid}: {item['status']} != {status}")
            got = item.get("closed_at", "missing")
            if closed == "expires_at":
                want = parse(item["expires_at"])
            elif closed == "R":
                want = self.reset_instant
            else:
                want = parse(closed)
            self.expect(got not in (None, "missing") and parse(got) == want, "seeded closed authorization closed_at (D-51)", f"{aid}: got {got}, want {want}")

    def check_reset_validation(self):
        """D-44/D-45: a future seeded created_at and a NEGATIVE opening are 422 and change nothing; a nonnegative opening is accepted.

        opening(u) = ending balance - net effect of the seeded payments on u. A receiver that ends below what it received
        has a negative opening (x_a ends at 30 after receiving 50: -20); a sender that ends at 0 after sending 50 opens at +50."""
        before = self.call("GET", "/me", self.tokens["u_0"])[1]["balance"]
        start = self.now()

        def fx(a_balance, b_balance, payments):
            users = [{"id": "x_a", "email": "xa@example.com", "password": PASSWORD, "display_name": "A", "handle": "xa", "balance": a_balance},
                     {"id": "x_b", "email": "xb@example.com", "password": PASSWORD, "display_name": "B", "handle": "xb", "balance": b_balance}]
            return {"currency": "EUR", "minor_units": 2, "users": users, "payments": payments}

        old = fmt(start - timedelta(hours=1))
        refused = {"future created_at": fx(100, 0, [{"id": "p_f", "from_user_id": "x_a", "to_user_id": "x_b", "amount": 1, "created_at": fmt(start + timedelta(hours=1))}]),
                   "negative opening (x_a ends at 30 after receiving 50: -20)": fx(30, 70, [{"id": "p_n", "from_user_id": "x_b", "to_user_id": "x_a", "amount": 50, "created_at": old}])}
        replaced = False
        for name, fixture in refused.items():
            status, resp = self.call("POST", "/_test/reset", body=fixture, timeout=20)
            replaced = replaced or status == 204
            self.expect(status == 422 and resp["error"]["code"] == "validation_failed", f"reset with a {name} must be 422 validation_failed", f"{status} {resp}")
        if replaced:        # the service accepted a bad fixture and replaced the state: start over from a clean one
            self.setup()
            return
        self.expect(self.call("GET", "/me", self.tokens["u_0"])[1].get("balance") == before, "a refused reset must change nothing", "")
        # control: x_b ends at 0 after SENDING 50 (opening +50) and x_a ends at 100 after receiving 50 (opening +50) is consistent
        status, resp = self.call("POST", "/_test/reset", body=fx(100, 0, [{"id": "p_ok", "from_user_id": "x_b", "to_user_id": "x_a", "amount": 50, "created_at": old}]), timeout=20)
        self.expect(status == 204, "a seeded history with nonnegative openings must be accepted (D-45)", f"{status} {resp}")
        self.setup()

    def check_snapshot_after_reset(self):
        if not self.snapshots:
            return
        user, token, _, _ = self.snapshots[0]
        fixture, _, _ = self.fixture()
        self.call("POST", "/_test/reset", body=fixture, timeout=20)
        status, body = self.call("POST", "/auth/login", body={"email": f"u{int(user.split('_')[1])}@example.com", "password": PASSWORD})
        status, _ = self.call("GET", "/statement", body["token"], params={"snapshot": token})
        self.expect(status == 404, "a snapshot token from before a reset must be 404 (D-50)", str(status))

    # ------------------------------------------------------------------ phases
    def lockstep(self, ops):
        weights = [(self.op_payment, 5), (self.op_correction, 7), (self.op_authorize, 2), (self.op_capture, 2), (self.op_void, 1),
                   (self.op_settlement, 1), (self.op_request_pay, 1)]
        names = {self.op_settlement: "settlement", self.op_request_pay: "request", self.op_capture: "capture", self.op_void: "void", self.op_authorize: "authorize",
                 self.op_correction: "correction"}
        pool = [fn for fn, w in weights for _ in range(w) if names.get(fn) not in self.skip]
        self.check_bad_instants()
        if "correction" not in self.skip:
            self.scenario_overdraft()
        for i in range(ops):
            self.rng.choice(pool)()
            if self.rng.random() < 0.15:
                time.sleep(self.rng.choice([0.4, 1.1]))
            if i % 4 == 0 or i == ops - 1:
                self.sync_auths()
                self.grid()
            if i % 10 == 9:
                self.check_snapshots()
                self.check_query_forms()
                if "correction" not in self.skip:
                    self.check_old_replays()
        self.sync_auths()
        self.check_snapshots()
        self.all_nonnegative()
        if self.protocol and "correction" not in self.skip:
            self.check_corrections_validation()
        if self.protocol:
            self.check_feed_unchanged()

    def same_revision_race(self):
        if "correction" in self.skip:
            return
        pays = [p for p in self.model.payments.values() if p.kind == "plain" and p.current().amount >= 2]
        if not pays:
            return
        pay = self.rng.choice(pays)
        n = len(pay.revs)
        effective = parse(fmt(min(pay.created_at, self.now() - timedelta(seconds=2))))
        amounts = [max(pay.current().amount - 1 - i % 2, 0) for i in range(20)]
        now = self.now()
        any_ok = any(self.model.correction_result(pay.id, pay.frm, n, a, effective, now) == "ok" for a in amounts)

        def go(i):
            body = {"expected_revision": n, "amount": amounts[i], "effective_at": fmt(effective), "reason": f"race {i}"}
            return body, self.call("POST", f"/payments/{pay.id}/corrections", self.tokens[pay.frm], body, self.key())

        with ThreadPoolExecutor(20) as pool:
            results = list(pool.map(go, range(20)))
        wins = [(b, r) for b, (s, r) in results if s == 201]
        self.note(f"race: 20 corrections of {pay.id} with expected_revision {n}: {len(wins)} won")
        self.expect(len(wins) <= 1, "concurrent corrections with the same expected revision: more than one succeeded (D-60)", f"{len(wins)} wins on {pay.id}")
        self.expect(len(wins) == 1 or not any_ok, "concurrent corrections: none won although the model accepts one (D-60)", f"{pay.id}")
        for body, resp in wins:
            self.see(resp["recorded_at"], "race recorded_at")
            self.add_rev(pay.id, resp, body["amount"], parse(body["effective_at"]), body["reason"])
        for body, (status, resp) in results:
            if status != 201:
                self.expect(resp["error"]["code"] in ("stale_revision", "insufficient_funds", "historical_overdraft"), "race loser answered unexpectedly", f"{status} {resp}")

    def concurrent(self, seconds):
        """50 in flight: writes interleaved with reads of views frozen in the past; frozen views must never move."""
        time.sleep(3.2)
        known = self.now().replace(microsecond=0) - timedelta(seconds=2)
        pool = [t for t in self.instants() if t <= known][-8:] + [parse(FAR_PAST)]
        views = [(u, fmtus(a), fmt(known)) for u in self.users for a in pool]
        baseline = {}
        for u, a, k in views:
            baseline[(u, a, k)] = self.me_view(u, a, k)
        self.expect(sum(baseline[(u, fmtus(pool[-1]), fmt(known))]["total"] for u in self.users) == self.seeded_total, "baseline totals != seeded total", "")
        stop = time.time() + seconds
        collected = {"payments": [], "revs": [], "auths": []}
        bad = []
        lock = self.lock

        def writer(w):
            rng = random.Random(self.seed * 1000 + w)
            while time.time() < stop:
                try:
                    kind = rng.random()
                    if kind < 0.5:
                        frm, to = rng.sample(self.users, 2)
                        body = {"to_handle": self.handles[to], "amount": rng.choice([1, 3, 10]), "note": "c"}
                        s, r = self.call("POST", "/payments", self.tokens[frm], body, self.key())
                        if s == 201:
                            with lock:
                                collected["payments"].append((r, frm, to, body["amount"]))
                    elif kind < 0.8 and "correction" not in self.skip:
                        with lock:
                            plain = [p for p in self.model.payments.values() if p.kind == "plain"]
                        pay = rng.choice(plain)
                        body = {"expected_revision": len(pay.revs), "amount": rng.choice([0, 1, 2]), "effective_at": fmt(known - timedelta(seconds=rng.randrange(0, 60))), "reason": "cc"}
                        s, r = self.call("POST", f"/payments/{pay.id}/corrections", self.tokens[pay.frm], body, self.key())
                        if s == 201:
                            with lock:
                                collected["revs"].append((pay.id, r, body))
                        elif s >= 500 or (s == 409 and r["error"]["code"] not in ("stale_revision", "insufficient_funds", "historical_overdraft")):
                            bad.append(f"correction {s} {r}")
                    else:
                        frm, to = rng.sample(self.users, 2)
                        s, r = self.call("POST", "/authorizations", self.tokens[frm], {"to_handle": self.handles[to], "amount": 20}, self.key())
                        if s == 201:
                            with lock:
                                collected["auths"].append((r, frm, to))
                except Exception as exc:  # noqa: BLE001
                    bad.append(repr(exc))

        def reader(w):
            rng = random.Random(self.seed * 2000 + w)
            while time.time() < stop:
                try:
                    u, a, k = rng.choice(views)
                    s, r = self.call("GET", "/me", self.tokens[u], params={"as_of": a, "known_at": k})
                    want = baseline[(u, a, k)]
                    got = {x: r.get(x) for x in ("balance", "total", "available", "held")}
                    if s != 200 or got != {x: want.get(x) for x in ("balance", "total", "available", "held")}:
                        bad.append(f"frozen view moved: {u} as_of={a} known_at={k}: {want} -> {s} {got}")
                    if "statement" in self.skip:
                        continue
                    s, r = self.call("GET", "/statement", self.tokens[u], params={"from": a, "to": fmt(known), "known_at": k, "limit": 200})
                    if s != 200:
                        bad.append(f"statement read failed {s}")
                    elif r["opening_balance"] + sum(e["delta"] for e in r["entries"]) != r["closing_balance"]:
                        bad.append(f"statement opening+deltas != closing for {u} from {a} known_at {k}")
                except Exception as exc:  # noqa: BLE001
                    bad.append(repr(exc))

        with ThreadPoolExecutor(50) as pool_:
            futures = [pool_.submit(writer, w) for w in range(20)] + [pool_.submit(reader, w) for w in range(30)]
            for f in futures:
                f.result()
        for message in bad[:5]:
            self.diverge("concurrent phase", message)
        for r, frm, to, amount in collected["payments"]:
            self.model.add_payment(r["payment_id"], frm, to, amount, parse(r["created_at"]))
        for r, frm, to in collected["auths"]:
            self.model.add_auth(r["authorization_id"], frm, to, 20, parse(r["created_at"]), parse(r["expires_at"]))
            self.auths.append(r["authorization_id"])
        for pid, r, body in sorted(collected["revs"], key=lambda x: (x[0], x[1]["revision"])):
            self.add_rev(pid, r, body["amount"], parse(body["effective_at"]), body["reason"])
        for u, a, k in views:
            now = self.me_view(u, a, k)
            self.expect(all(now[x] == baseline[(u, a, k)][x] for x in ("balance", "total", "available", "held")),
                        "a frozen historical view changed after the concurrent writes", f"{u} as_of={a} known_at={k}")
        self.note(f"concurrent phase: {len(collected['payments'])} payments, {len(collected['revs'])} corrections, {len(collected['auths'])} authorizations")
        self.sync_auths()
        self.grid(24)
        self.all_nonnegative()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upgrade", type=int, choices=(1, 2), help="populate a frozen stage-1/2 service (--source), export it, import into the target, then diff")
    ap.add_argument("--source", help="URL of the frozen stage-1/2 service to populate for --upgrade (your own copy)")
    ap.add_argument("--source-ops", type=int, default=60)
    ap.add_argument("--ops", type=int, default=120)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("DIFF_SEED", random.randrange(1 << 30))))
    ap.add_argument("--concurrent", type=float, default=8, help="seconds of the 50-way concurrent phase (0 = skip)")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--skip", default="", help="parts to leave out: settlement,request,capture,void,authorize,correction,statement")
    ap.add_argument("--no-protocol", action="store_true", help="skip shape/validation checks (for stand-in services)")
    args = ap.parse_args()
    base = os.environ.get("TARGET_URL")
    if not base:
        print("TARGET_URL is required", file=sys.stderr)
        return 2
    run = Run(base, args.seed, args.keep_going)
    run.skip = set(filter(None, args.skip.split(",")))
    run.protocol = not args.no_protocol
    began = time.time()
    try:
        if args.upgrade:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from upgrade import populate
            data = populate(args.source, args.upgrade, args.seed, args.source_ops)
            data["stage"] = args.upgrade
            status, resp = run.call("POST", "/_test/import", body=data["export"], timeout=60)
            run.expect(status == 204, f"a stage {args.upgrade} export must import (D-52)", f"{status} {resp}")
            run.setup_upgrade(data)
            run.check_import()
            run.check_linked()
        else:
            run.setup()
            if run.protocol:
                run.check_seeded_closed()
                run.check_reset_validation()
        run.grid(20)
        run.lockstep(args.ops)
        run.same_revision_race()
        if args.concurrent:
            run.concurrent(args.concurrent)
        run.grid(20)
        if run.protocol:
            run.check_snapshot_after_reset()
    except Divergence as d:
        print(str(d))
    run.http.close()
    elapsed = time.time() - began
    for text in (run.findings if args.keep_going else run.findings[1:]):
        print("\n" + (text if args.keep_going and text is run.findings[0] else text.split("-- operations")[0]))
    print("correction outcomes seen:", dict(sorted(run.outcomes.items())))
    print(f"\n{run.queries} historical reads, {len(run.log)} operations, {len(run.snapshots)} snapshots, {elapsed:.0f}s, seed {args.seed}: "
          f"{'FAIL (' + str(len(run.findings)) + ' divergences)' if run.findings else 'PASS no divergence'}")
    return 1 if run.findings else 0


if __name__ == "__main__":
    sys.exit(main())
