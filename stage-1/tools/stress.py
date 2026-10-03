#!/usr/bin/env python3
"""Concurrency and retry stress tool for a Pocketful stage 1 service.

    TARGET_URL=http://127.0.0.1:8080 python stage-1/tools/stress.py

Environment: TARGET_URL (required), STRESS_SECONDS (mixed load length, default 20),
STRESS_SEED (default random, printed). Only stdlib and httpx are used.

Every scenario resets the service with its own fixture, drives up to 50 requests in
flight, then checks the money and idempotency invariants of the specification:
balances never negative (also sampled during the load), balances sum to the seeded
total, balances equal seeded balance plus the payments the service confirmed with 201,
a request moves money at most once, replays return 200 with the original body, a
settlement is all or none, no 5xx, every 4xx carries the JSON error envelope.
Exit code is 0 only when every scenario passes.
"""
import asyncio
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx

PASSWORD = "correct horse"
MAX_IN_FLIGHT = 50
REQ_TIMEOUT = 5.0
RESET_TIMEOUT = 10.0
MAX_MESSAGES = 6
PAGE = 200


@dataclass
class Resp:
    status: int
    json: object
    text: str


def _shuffled(obj, rng):
    if isinstance(obj, dict):
        items = list(obj.items())
        rng.shuffle(items)
        return {k: _shuffled(v, rng) for k, v in items}
    if isinstance(obj, list):
        return [_shuffled(v, rng) for v in obj]
    return obj


class Api:
    def __init__(self, base):
        self.client = httpx.AsyncClient(
            base_url=base,
            limits=httpx.Limits(max_connections=MAX_IN_FLIGHT + 5),
            timeout=REQ_TIMEOUT,
        )
        self.sem = asyncio.Semaphore(MAX_IN_FLIGHT)
        self.rng = random.Random()
        self.five_xx, self.bad_envelope, self.transport = [], [], []
        self.count = 0

    async def call(self, method, path, *, token=None, body=None, key=None,
                   shuffle=False, raw=None, timeout=REQ_TIMEOUT):
        headers = {}
        content = None
        if raw is not None:
            content = raw
        elif body is not None:
            if shuffle:
                content = json.dumps(_shuffled(body, self.rng),
                                     indent=self.rng.choice([None, 1, 3]))
            else:
                content = json.dumps(body)
        if content is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key is not None:
            headers["Idempotency-Key"] = key
        async with self.sem:
            self.count += 1
            try:
                r = await self.client.request(method, path, headers=headers,
                                              content=content, timeout=timeout)
            except Exception as exc:  # timeout (>5 s) or connection failure
                self.transport.append(f"{method} {path}: {exc!r}")
                return Resp(0, None, repr(exc))
        try:
            data = r.json()
        except ValueError:
            data = None
        tag = f"{method} {path} -> {r.status_code} {r.text[:100]}"
        if r.status_code >= 500:
            self.five_xx.append(tag)
        elif r.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            if not (isinstance(err, dict) and isinstance(err.get("code"), str)
                    and isinstance(err.get("message"), str)):
                self.bad_envelope.append(tag)
        return Resp(r.status_code, data, r.text)


class Scenario:
    def __init__(self, name):
        self.name = name
        self.fails = []
        self.fail_count = 0
        self.notes = []

    def check(self, cond, msg):
        if not cond:
            self.fail_count += 1
            if len(self.fails) < MAX_MESSAGES:
                self.fails.append(msg)
        return bool(cond)

    def expect(self, r, allowed, what):
        return self.check(r.status in allowed,
                          f"{what}: got {r.status} {r.text[:120]}, wanted {sorted(allowed)}")

    def code(self, r, status, code, what):
        err = r.json.get("error") if isinstance(r.json, dict) else None
        ok = r.status == status and isinstance(err, dict) and err.get("code") == code
        return self.check(ok, f"{what}: got {r.status} {r.text[:120]}, wanted {status} {code}")


@dataclass
class User:
    id: str
    handle: str
    token: str = ""


class Ledger:
    """Payments the service confirmed with 201, deduplicated by payment id."""

    def __init__(self, initial):
        self.initial = dict(initial)
        self.payments = {}

    def add(self, p):
        self.payments.setdefault(p["payment_id"], p)

    def expected(self):
        bal = dict(self.initial)
        for p in self.payments.values():
            bal[p["from_user_id"]] -= p["amount"]
            bal[p["to_user_id"]] += p["amount"]
        return bal


class World:
    def __init__(self, api, users, initial):
        self.api = api
        self.users = users
        self.by_handle = {u.handle: u for u in users}
        self.total = sum(initial.values())
        self.ledger = Ledger(initial)

    def u(self, handle):
        return self.by_handle[handle]

    async def balances(self, sc):
        rs = await asyncio.gather(*[self.api.call("GET", "/me", token=u.token) for u in self.users])
        out = {}
        for u, r in zip(self.users, rs):
            if sc.expect(r, {200}, f"GET /me {u.handle}"):
                out[u.id] = r.json["balance"]
        return out

    async def verify(self, sc, label="final"):
        bal = await self.balances(sc)
        for uid, b in bal.items():
            sc.check(isinstance(b, int) and b >= 0, f"{label}: {uid} balance {b} is negative")
        sc.check(sum(bal.values()) == self.total,
                 f"{label}: balances sum {sum(bal.values())}, seeded {self.total}")
        for uid, want in self.ledger.expected().items():
            if uid in bal:
                sc.check(bal[uid] == want,
                         f"{label}: {uid} balance {bal[uid]} != seeded + confirmed payments {want}")
        return bal


async def setup(api, sc, balances, operators=()):
    users = [User(f"u_{h}", h) for h in balances]
    fixture = {
        "currency": "EUR", "minor_units": 2,
        "users": [{"id": u.id, "email": f"{u.handle}@example.com", "password": PASSWORD,
                   "display_name": u.handle.upper(), "handle": u.handle,
                   "balance": balances[u.handle]} for u in users],
        "payments": [], "requests": [],
        "settlement_operator_ids": [f"u_{h}" for h in operators],
    }
    r = await api.call("POST", "/_test/reset", body=fixture, timeout=RESET_TIMEOUT)
    if r.status != 204:
        raise RuntimeError(f"reset returned {r.status} {r.text[:150]}")
    logins = await asyncio.gather(*[api.call("POST", "/auth/login", body={
        "email": f"{u.handle}@example.com", "password": PASSWORD}) for u in users])
    for u, r in zip(users, logins):
        if r.status != 200 or not isinstance(r.json, dict) or "token" not in r.json:
            raise RuntimeError(f"login {u.handle} returned {r.status} {r.text[:150]}")
        u.token = r.json["token"]
    return World(api, users, {u.id: balances[u.handle] for u in users})


async def burst(factories):
    """Start every coroutine factory at once and return their results in order."""
    go = asyncio.Event()

    async def run(f):
        await go.wait()
        return await f()

    tasks = [asyncio.create_task(run(f)) for f in factories]
    await asyncio.sleep(0.1)
    go.set()
    return await asyncio.gather(*tasks)


class Sampler:
    """Polls GET /me while a load runs and fails on any negative or oversized balance."""

    def __init__(self, world, sc, workers=3):
        self.w, self.sc, self.stop, self.samples = world, sc, False, 0
        self.tasks = [asyncio.create_task(self._loop()) for _ in range(workers)]

    async def _loop(self):
        while not self.stop:
            u = self.w.api.rng.choice(self.w.users)
            r = await self.w.api.call("GET", "/me", token=u.token)
            if r.status == 200:
                self.samples += 1
                b = r.json["balance"]
                self.sc.check(b >= 0, f"sampled {u.id} balance {b} during load (negative)")
                self.sc.check(b <= self.w.total, f"sampled {u.id} balance {b} > seeded total")
            await asyncio.sleep(0.005)

    async def finish(self):
        self.stop = True
        await asyncio.gather(*self.tasks)
        self.sc.notes.append(f"{self.samples} balance samples")


def key():
    return "k-" + uuid.uuid4().hex


def split_replays(sc, rs, what, want_first=201):
    """Exactly one 201 and the rest 200 with the same JSON value; returns the 201 response."""
    firsts = [r for r in rs if r.status == want_first]
    replays = [r for r in rs if r.status == 200]
    sc.check(len(firsts) == 1, f"{what}: {len(firsts)} responses were 201, wanted exactly 1")
    sc.check(len(firsts) + len(replays) == len(rs),
             f"{what}: statuses {sorted({r.status for r in rs})}, wanted only 201 and 200")
    if firsts:
        for r in replays:
            if not sc.check(r.json == firsts[0].json, f"{what}: replay body differs from original"):
                break
    return firsts[0] if firsts else None


# ---------------------------------------------------------------- scenario a

async def scen_a(api, sc):
    w = await setup(api, sc, {"src": 1000, **{f"r{i}": 0 for i in range(5)}})
    src = w.u("src")
    smp = Sampler(w, sc)
    rs = await burst([
        (lambda i=i: api.call("POST", "/payments", token=src.token, key=key(),
                              body={"to_handle": f"r{i % 5}", "amount": 100, "note": "drain"}))
        for i in range(50)])
    await smp.finish()
    wins = [r for r in rs if r.status == 201]
    for r in rs:
        if r.status == 201:
            w.ledger.add(r.json)
        else:
            sc.code(r, 409, "insufficient_funds", "drain payment")
    sc.check(len(wins) == 10, f"{len(wins)} payments succeeded from a 1000 wallet at 100 each, wanted 10")
    bal = await w.verify(sc)
    sc.check(bal.get(src.id) == 1000 - 100 * len(wins), "source debit != successes * amount")
    sc.notes.append(f"{len(wins)} ok / {50 - len(wins)} refused")


# ---------------------------------------------------------------- scenario b

async def scen_b(api, sc):
    w = await setup(api, sc, {"ada": 1000, "bob": 0, "cy": 100})
    ada, bob, cy = w.u("ada"), w.u("bob"), w.u("cy")
    k = key()
    body = {"to_handle": "bob", "amount": 100, "note": "same key", "visibility": "public"}
    rs = await burst([(lambda: api.call("POST", "/payments", token=ada.token, key=k,
                                        body=body, shuffle=True)) for _ in range(50)])
    first = split_replays(sc, rs, "same-key payment")
    if first:
        w.ledger.add(first.json)
    bal = await w.verify(sc)
    sc.check(bal.get(ada.id) == 900, f"money moved {1000 - bal.get(ada.id, 0)} times 1, wanted once (900 left)")
    r = await api.call("POST", "/payments", token=ada.token, key=k, body={**body, "amount": 101})
    sc.code(r, 409, "idempotency_key_reuse", "same key, different body")
    r = await api.call("POST", "/requests", token=ada.token, key=k,
                       body={"payer_handle": "bob", "amount": 100})
    sc.expect(r, {201}, "same key on a different path is a new request")
    r = await api.call("POST", "/payments", token=cy.token, key=k, body={**body, "to_handle": "ada"})
    sc.expect(r, {201}, "same key from a different user is independent")
    r = await api.call("POST", "/payments", token=ada.token, body=body)
    sc.code(r, 400, "missing_idempotency_key", "no Idempotency-Key header")
    r = await api.call("POST", "/payments", token=ada.token, key="x" * 256, body=body)
    sc.code(r, 422, "validation_failed", "256 character key")
    ka = key()
    r = await api.call("POST", "/payments", token=ada.token, key=ka, body={**body, "amount": 0})
    sc.code(r, 422, "validation_failed", "invalid amount")
    r = await api.call("POST", "/payments", token=ada.token, key=ka, body=body)
    sc.expect(r, {201}, "key reused after a 4xx is a first use")


# ---------------------------------------------------------------- scenario c

async def pay_race(api, sc):
    w = await setup(api, sc, {"req": 0, "payer": 1000, "other": 0})
    req, payer = w.u("req"), w.u("payer")
    r = await api.call("POST", "/requests", token=req.token, key=key(),
                       body={"payer_handle": "payer", "amount": 300, "note": "taxi"})
    if not sc.expect(r, {201}, "create request"):
        return
    rid = r.json["request_id"]
    keys = [key() for _ in range(50)]
    vis = ["public", "private"]
    rs = await burst([
        (lambda i=i: api.call("POST", f"/requests/{rid}/pay", token=payer.token, key=keys[i],
                              body={"visibility": vis[i % 2]})) for i in range(50)])
    win = [i for i, r in enumerate(rs) if r.status == 201]
    sc.check(len(win) == 1, f"{len(win)} pay calls returned 201, wanted exactly 1")
    for r in rs:
        if r.status == 201:
            w.ledger.add(r.json)
            sc.check(r.json.get("request_id") == rid and r.json.get("amount") == 300,
                     "payment does not reference the request or amount")
        else:
            sc.code(r, 409, "request_not_pending", "losing pay")
    bal = await w.verify(sc)
    sc.check(bal.get(payer.id) == 700 and bal.get(req.id) == 300,
             f"request moved money other than once: payer {bal.get(payer.id)}, requester {bal.get(req.id)}")
    if win:
        i = win[0]
        body = {"visibility": vis[i % 2]}
        rs2 = await burst([(lambda: api.call("POST", f"/requests/{rid}/pay", token=payer.token,
                                             key=keys[i], body=body, shuffle=True)) for _ in range(20)])
        for r in rs2:
            sc.check(r.status == 200 and r.json == rs[i].json,
                     f"replay of the winning pay: {r.status} {r.text[:100]}")
        other = {} if i % 2 else {"visibility": "public"}
        if other != body:
            r = await api.call("POST", f"/requests/{rid}/pay", token=payer.token, key=keys[i], body=other)
            sc.code(r, 409, "idempotency_key_reuse", "pay replay with a different body")
        await w.verify(sc, "after replays")
    g = await api.call("GET", "/requests", token=req.token)
    if sc.expect(g, {200}, "GET /requests"):
        mine = [x for x in g.json["requests"] if x["request_id"] == rid]
        sc.check(len(mine) == 1 and mine[0]["status"] == "paid"
                 and mine[0]["payment_id"] == (rs[win[0]].json["payment_id"] if win else None),
                 "request is not paid with the winning payment id")
    sc.notes.append("50 pay calls, 1 request")


async def terminal_race(api, sc):
    """Five requests, each raced by 10 operations: 4 pay, 3 decline, 3 cancel."""
    w = await setup(api, sc, {"req": 0, "payer": 1000})
    req, payer = w.u("req"), w.u("payer")
    rids = []
    for _ in range(5):
        r = await api.call("POST", "/requests", token=req.token, key=key(),
                           body={"payer_handle": "payer", "amount": 100})
        if not sc.expect(r, {201}, "create request"):
            return
        rids.append(r.json["request_id"])
    jobs = []
    for rid in rids:
        for n in range(4):
            jobs.append((rid, "pay", lambda rid=rid: api.call(
                "POST", f"/requests/{rid}/pay", token=payer.token, key=key(), body={})))
        for n in range(3):
            jobs.append((rid, "decline", lambda rid=rid: api.call(
                "POST", f"/requests/{rid}/decline", token=payer.token)))
        for n in range(3):
            jobs.append((rid, "cancel", lambda rid=rid: api.call(
                "POST", f"/requests/{rid}/cancel", token=req.token)))
    random.shuffle(jobs)
    rs = await burst([j[2] for j in jobs])
    outcome = {rid: set() for rid in rids}
    for (rid, kind, _), r in zip(jobs, rs):
        if kind == "pay" and r.status == 201:
            outcome[rid].add("paid")
            w.ledger.add(r.json)
        elif kind == "decline" and r.status == 200:
            outcome[rid].add("declined")
        elif kind == "cancel" and r.status == 200:
            outcome[rid].add("cancelled")
        elif not (r.status == 409 and isinstance(r.json, dict)
                  and r.json.get("error", {}).get("code") in ("request_not_pending",)):
            sc.check(False, f"{kind} race: {r.status} {r.text[:100]}")
    g = await api.call("GET", "/requests?limit=200", token=req.token)
    final = {x["request_id"]: x["status"] for x in g.json["requests"]} if g.status == 200 else {}
    for rid in rids:
        sc.check(len(outcome[rid]) == 1 and final.get(rid) in outcome[rid],
                 f"{rid}: successful outcomes {sorted(outcome[rid])}, final status {final.get(rid)}")
    await w.verify(sc)
    sc.notes.append("5 requests x 10 racing ops")


# ---------------------------------------------------------------- scenario d

def tr(frm, to, amount, **extra):
    return {"from_handle": frm, "to_handle": to, "amount": amount, **extra}


async def scen_d1(api, sc):
    w = await setup(api, sc, {"op": 0, "a": 100, "b": 0, "c": 0, "d": 0, "e": 0}, operators=["op"])
    op, a, e = w.u("op"), w.u("a"), w.u("e")
    batch = {"transfers": [tr("a", "b", 100)]}
    r = await api.call("POST", "/settlements", key=key(), body=batch)
    sc.code(r, 401, "unauthenticated", "settlement without token")
    r = await api.call("POST", "/settlements", token=a.token, key=key(), body=batch)
    sc.code(r, 403, "forbidden", "settlement by a non operator")
    r = await api.call("POST", "/settlements", token=op.token, body=batch)
    sc.code(r, 400, "missing_idempotency_key", "settlement without key")
    r = await api.call("GET", "/requests", token=op.token)
    sc.check(r.status == 200 and r.json["requests"] == [], "operator sees other users' requests")
    chain = {"transfers": [tr("a", "b", 100), tr("b", "c", 100)]}
    r = await api.call("POST", "/settlements", token=op.token, key=key(), body=chain)
    if sc.expect(r, {201}, "chain affordable by net") and isinstance(r.json, dict):
        ps = r.json.get("payments", [])
        sc.check(len(ps) == 2 and [p["from_handle"] for p in ps] == ["a", "b"], "members not in input order")
        sc.check(all(p.get("settlement_id") == r.json.get("settlement_id") and p.get("request_id") is None
                     and p.get("created_at") == r.json.get("committed_at") for p in ps),
                 "member settlement_id / request_id / created_at wrong")
        for p in ps:
            w.ledger.add(p)
    bal = await w.verify(sc, "after chain")
    sc.check(bal.get(a.id) == 0 and bal.get(w.u("c").id) == 100, "chain balances wrong")
    for name, transfers, status, code in [
        ("net unaffordable", [tr("a", "b", 1)], 409, "insufficient_funds"),
        ("unknown handle beats funds", [tr("a", "b", 999), tr("nobody", "b", 1)], 404, "not_found"),
        ("self transfer beats funds", [tr("a", "b", 999), tr("b", "b", 1)], 422, "self_payment"),
        ("empty batch", [], 422, "validation_failed"),
        ("33 transfers", [tr("c", "d", 1)] * 33, 422, "validation_failed"),
        ("zero amount", [tr("c", "d", 0)], 422, "validation_failed"),
        ("bad visibility", [tr("c", "d", 1, visibility="friends")], 422, "validation_failed"),
    ]:
        r = await api.call("POST", "/settlements", token=op.token, key=key(), body={"transfers": transfers})
        sc.code(r, status, code, name)
    await w.verify(sc, "after refusals")
    k = key()
    r = await api.call("POST", "/settlements", token=op.token, key=k, body={"transfers": []})
    sc.code(r, 422, "validation_failed", "invalid batch")
    priv = {"transfers": [tr("c", "d", 10, visibility="private")]}
    r = await api.call("POST", "/settlements", token=op.token, key=k, body=priv)
    if sc.expect(r, {201}, "failed validation claims no key"):
        for p in r.json["payments"]:
            w.ledger.add(p)
        pid = r.json["payments"][0]["payment_id"]
        feeds = await asyncio.gather(*[api.call("GET", "/activity", token=u.token) for u in (w.u("c"), w.u("d"), e)])
        seen = [pid in [p["payment_id"] for p in f.json["payments"]] if f.status == 200 else None for f in feeds]
        sc.check(seen == [True, True, False], f"private settlement member visibility c,d,e = {seen}")
        sc.check(all(p["visibility"] == "private" for p in r.json["payments"]), "visibility not kept")
    await w.verify(sc)


def random_batch(rng, handles):
    out = []
    for _ in range(rng.randint(1, 6)):
        f, t = rng.sample(handles, 2)
        out.append(tr(f, t, rng.randint(1, 150)))
    return {"transfers": out}


async def all_settlement_payments(api, token):
    found, offset = [], 0
    while True:
        r = await api.call("GET", f"/activity?limit={PAGE}&offset={offset}", token=token)
        if r.status != 200:
            return None
        found += [p for p in r.json["payments"] if p.get("settlement_id")]
        if not r.json["has_more"]:
            return found
        offset += PAGE


async def scen_d2(api, sc):
    handles = [f"w{i}" for i in range(6)]
    balances = {"op": 0, **dict(zip(handles, [200, 100, 50, 0, 0, 300]))}
    w = await setup(api, sc, balances, operators=["op"])
    op = w.u("op")
    batches = [random_batch(api.rng, handles) for _ in range(50)]
    smp = Sampler(w, sc)
    rs = await burst([(lambda b=b: api.call("POST", "/settlements", token=op.token, key=key(), body=b))
                      for b in batches])
    await smp.finish()
    committed = {}
    for b, r in zip(batches, rs):
        if r.status == 201:
            committed[r.json["settlement_id"]] = len(b["transfers"])
            sc.check(len(r.json["payments"]) == len(b["transfers"]), "receipt has wrong member count")
            for p, t in zip(r.json["payments"], b["transfers"]):
                sc.check(p["from_handle"] == t["from_handle"] and p["to_handle"] == t["to_handle"]
                         and p["amount"] == t["amount"], "member does not match input order")
                w.ledger.add(p)
        else:
            sc.code(r, 409, "insufficient_funds", "unaffordable batch")
    await w.verify(sc)
    feed = await all_settlement_payments(api, op.token)
    if sc.check(feed is not None, "GET /activity failed"):
        per = {}
        for p in feed:
            per[p["settlement_id"]] = per.get(p["settlement_id"], 0) + 1
        sc.check(per == committed,
                 f"activity shows settlements {sorted(per.items())[:4]}, receipts {sorted(committed.items())[:4]}: "
                 "a refused batch left payments or a committed one is partial")
    sc.check(0 < len(committed) < 50, f"{len(committed)} of 50 batches committed: load has no mix of outcomes")
    sc.notes.append(f"{len(committed)} committed / {50 - len(committed)} refused")


async def scen_d3(api, sc):
    w = await setup(api, sc, {"op": 0, "a": 300, "b": 0, "c": 0}, operators=["op"])
    op = w.u("op")
    batch = {"transfers": [tr("a", "b", 100), tr("a", "c", 50, note="x")]}
    k = key()
    rs = await burst([(lambda: api.call("POST", "/settlements", token=op.token, key=k,
                                        body=batch, shuffle=True)) for _ in range(50)])
    first = split_replays(sc, rs, "same-key settlement")
    if first:
        for p in first.json["payments"]:
            w.ledger.add(p)
    bal = await w.verify(sc)
    sc.check(bal.get(w.u("a").id) == 150, "same-key settlement applied more or less than once")


# ---------------------------------------------------------------- scenario e

class Mixed:
    WEIGHTS = [("payment", 14), ("request", 10), ("pay", 12), ("decline", 4), ("cancel", 4),
               ("split", 6), ("activity", 8), ("listing", 6), ("me", 5), ("bad", 4),
               ("settle", 6), ("replay", 8)]

    def __init__(self, api, sc, w, seconds):
        self.api, self.sc, self.w, self.seconds = api, sc, w, seconds
        self.rng = random.Random(api.rng.random())
        self.reqs = {}        # request id -> (requester User, payer User)
        self.observed = {}    # request id -> terminal statuses the service confirmed
        self.successes = []   # (path, token, key, body, response) for replays
        self.ops = 0
        self.op_op = w.u("u0")

    def pick(self, *not_users):
        return self.rng.choice([u for u in self.w.users if u not in not_users])

    def remember(self, path, user, k, body, r):
        if len(self.successes) < 400:
            self.successes.append((path, user.token, k, body, r.json))

    async def run(self):
        end = time.monotonic() + self.seconds
        ops = [n for n, wt in self.WEIGHTS for _ in range(wt)]

        async def worker():
            while time.monotonic() < end:
                self.ops += 1
                await getattr(self, "op_" + self.rng.choice(ops))()

        smp = Sampler(self.w, self.sc, workers=5)
        await asyncio.gather(*[worker() for _ in range(MAX_IN_FLIGHT - 5)])
        await smp.finish()

    async def op_payment(self):
        a, b = self.pick(), None
        b = self.pick(a)
        amt = self.rng.choice([1, 5, 50, 100, 250, self.rng.randint(1, 600)])
        body = {"to_handle": b.handle, "amount": amt, "note": "mix",
                "visibility": self.rng.choice(["public", "private"])}
        k = key()
        r = await self.api.call("POST", "/payments", token=a.token, key=k, body=body)
        if r.status == 201:
            self.w.ledger.add(r.json)
            self.sc.check(r.json["from_user_id"] == a.id and r.json["to_user_id"] == b.id
                          and r.json["amount"] == amt and r.json["visibility"] == body["visibility"],
                          f"payment receipt does not match request: {r.text[:120]}")
            self.remember("/payments", a, k, body, r)
        else:
            self.sc.code(r, 409, "insufficient_funds", "mixed payment")

    async def op_request(self):
        a = self.pick()
        b = self.pick(a)
        body = {"payer_handle": b.handle, "amount": self.rng.randint(1, 800), "note": "mix"}
        k = key()
        r = await self.api.call("POST", "/requests", token=a.token, key=k, body=body)
        if self.sc.expect(r, {201}, "mixed request"):
            self.sc.check(r.json["status"] == "pending" and r.json["payment_id"] is None, "new request not pending")
            self.reqs[r.json["request_id"]] = (a, b)
            self.remember("/requests", a, k, body, r)

    def some_request(self):
        return self.rng.choice(list(self.reqs)) if self.reqs else None

    def terminal(self, rid, status):
        self.observed.setdefault(rid, set()).add(status)

    async def op_pay(self):
        rid = self.some_request()
        if rid is None:
            return
        requester, payer = self.reqs[rid]
        caller = payer if self.rng.random() < 0.85 else self.pick()
        body = self.rng.choice([{}, {"visibility": "private"}, {"visibility": "public"}])
        k = key()
        r = await self.api.call("POST", f"/requests/{rid}/pay", token=caller.token, key=k, body=body)
        if caller is not payer:
            self.sc.code(r, 403, "forbidden", "pay by a non payer")
        elif r.status == 201:
            self.w.ledger.add(r.json)
            self.sc.check(r.json["request_id"] == rid and r.json["from_user_id"] == payer.id
                          and r.json["to_user_id"] == requester.id, "payment does not match its request")
            self.terminal(rid, "paid")
            self.remember(f"/requests/{rid}/pay", caller, k, body, r)
        elif r.status == 409:
            code = r.json["error"]["code"] if isinstance(r.json, dict) else None
            self.sc.check(code in ("request_not_pending", "insufficient_funds"), f"pay 409 code {code}")
        else:
            self.sc.expect(r, {201, 409}, "mixed pay")

    async def _close(self, verb, status):
        rid = self.some_request()
        if rid is None:
            return
        requester, payer = self.reqs[rid]
        owner = payer if verb == "decline" else requester
        caller = owner if self.rng.random() < 0.85 else self.pick()
        r = await self.api.call("POST", f"/requests/{rid}/{verb}", token=caller.token)
        if caller is not owner:
            self.sc.code(r, 403, "forbidden", f"{verb} by the wrong party")
        elif r.status == 200:
            self.sc.check(r.json["status"] == status, f"{verb} returned status {r.json['status']}")
            self.terminal(rid, status)
        else:
            self.sc.code(r, 409, "request_not_pending", verb)

    async def op_decline(self):
        await self._close("decline", "declined")

    async def op_cancel(self):
        await self._close("cancel", "cancelled")

    async def op_split(self):
        caller = self.pick()
        group = self.rng.sample(self.w.users, self.rng.randint(1, 4))
        amt = self.rng.randint(1, 2000)
        body = {"amount": amt, "participant_handles": [u.handle for u in group], "note": "mix"}
        k = key()
        r = await self.api.call("POST", "/splits", token=caller.token, key=k, body=body)
        if not self.sc.expect(r, {201}, "mixed split"):
            return
        n, rem = len(group), amt % len(group)
        want = [amt // n + (1 if i < rem else 0) for i in range(n)]
        self.sc.check([s["amount"] for s in r.json["shares"]] == want, f"split shares {r.json['shares']} != {want}")
        others = [u for u in group if u is not caller]
        self.sc.check([q["payer_handle"] for q in r.json["requests"]] == [u.handle for u in others],
                      "split requests do not cover the other participants in order")
        for q, u in zip(r.json["requests"], others):
            self.reqs[q["request_id"]] = (caller, u)
        self.remember("/splits", caller, k, body, r)

    def visible(self, p, me):
        return p["visibility"] == "public" or me.id in (p["from_user_id"], p["to_user_id"])

    async def op_activity(self):
        me = self.pick()
        limit, offset = self.rng.choice([1, 5, 50, 200]), self.rng.randint(0, 20)
        r = await self.api.call("GET", f"/activity?limit={limit}&offset={offset}", token=me.token)
        if self.sc.expect(r, {200}, "GET /activity"):
            ps = r.json["payments"]
            self.sc.check(len(ps) <= limit and isinstance(r.json["has_more"], bool), "activity page shape")
            self.sc.check(all(self.visible(p, me) for p in ps), "activity shows a private payment to a third party")

    async def op_listing(self):
        me = self.pick()
        d = self.rng.choice([None, "incoming", "outgoing"])
        s = self.rng.choice([None, "pending", "paid", "declined", "cancelled"])
        qs = "".join(f"&{k}={v}" for k, v in (("direction", d), ("status", s)) if v)
        r = await self.api.call("GET", f"/requests?limit={self.rng.choice([5, 50, 200])}{qs}", token=me.token)
        if not self.sc.expect(r, {200}, "GET /requests"):
            return
        items = r.json["requests"]
        for q in items:
            mine = {"incoming": q["payer_id"] == me.id, "outgoing": q["requester_id"] == me.id,
                    None: me.id in (q["payer_id"], q["requester_id"])}[d]
            self.sc.check(mine and (s is None or q["status"] == s), "GET /requests returned a request outside the filter")
        stamps = [datetime.fromisoformat(q["created_at"]) for q in items]
        self.sc.check(stamps == sorted(stamps, reverse=True), "GET /requests not newest first")

    async def op_me(self):
        u = self.pick()
        r = await self.api.call("GET", "/me", token=u.token)
        if self.sc.expect(r, {200}, "GET /me"):
            self.sc.check(0 <= r.json["balance"] <= self.w.total, f"balance {r.json['balance']} out of range")

    async def op_bad(self):
        a, b = self.pick(), None
        b = self.pick(a)
        k = key()
        case = self.rng.choice([
            ({"to_handle": b.handle, "amount": "10"}, 422, "validation_failed"),
            ({"to_handle": b.handle, "amount": True}, 422, "validation_failed"),
            ({"to_handle": b.handle, "amount": 0}, 422, "validation_failed"),
            ({"to_handle": b.handle, "amount": 1000000001}, 422, "validation_failed"),
            ({"to_handle": b.handle, "amount": 10, "note": None}, 422, "validation_failed"),
            ({"to_handle": a.handle, "amount": 10}, 422, "self_payment"),
            ({"to_handle": "no_such_user", "amount": 10}, 404, "not_found"),
            ({"to_handle": b.handle, "amount": 10, "visibility": "friends"}, 422, "validation_failed"),
        ])
        r = await self.api.call("POST", "/payments", token=a.token, key=k, body=case[0])
        self.sc.code(r, case[1], case[2], f"bad payment {case[0]}")

    async def op_settle(self):
        handles = [u.handle for u in self.w.users]
        batch = random_batch(self.rng, handles)
        for t in batch["transfers"]:
            t["amount"] = self.rng.randint(1, 120)
        k = key()
        r = await self.api.call("POST", "/settlements", token=self.op_op.token, key=k, body=batch)
        if r.status == 201:
            self.sc.check(len(r.json["payments"]) == len(batch["transfers"]), "settlement member count")
            for p in r.json["payments"]:
                self.w.ledger.add(p)
            self.remember("/settlements", self.op_op, k, batch, r)
        else:
            self.sc.code(r, 409, "insufficient_funds", "mixed settlement")

    async def op_replay(self):
        if not self.successes:
            return
        path, token, k, body, original = self.rng.choice(self.successes)
        r = await self.api.call("POST", path, token=token, key=k, body=body, shuffle=True)
        self.sc.check(r.status == 200 and r.json == original,
                      f"replay of {path}: {r.status} {r.text[:100]} (wanted 200 and the original body)")

    async def final_checks(self):
        sc, w = self.sc, self.w
        await w.verify(sc)
        by_req = {}
        for p in w.ledger.payments.values():
            if p.get("request_id"):
                by_req.setdefault(p["request_id"], []).append(p)
        sc.check(all(len(v) == 1 for v in by_req.values()),
                 f"requests that moved money more than once: {[k for k, v in by_req.items() if len(v) > 1][:3]}")
        final = {}
        for u in w.users:
            offset = 0
            while True:
                r = await self.api.call("GET", f"/requests?limit={PAGE}&offset={offset}", token=u.token)
                if r.status != 200:
                    sc.expect(r, {200}, "final GET /requests")
                    break
                final.update({q["request_id"]: q for q in r.json["requests"]})
                if not r.json["has_more"]:
                    break
                offset += PAGE
        sc.check(set(self.reqs) <= set(final), "a created request is missing from GET /requests")
        for rid, q in final.items():
            paid = by_req.get(rid, [])
            sc.check((q["status"] == "paid") == bool(paid), f"{rid}: status {q['status']} but {len(paid)} payments")
            if paid:
                sc.check(q["payment_id"] == paid[0]["payment_id"] and q["amount"] == paid[0]["amount"],
                         f"{rid}: paid request does not carry its payment")
            seen = self.observed.get(rid, set())
            sc.check(len(seen) <= 1 and (not seen or q["status"] in seen),
                     f"{rid}: confirmed outcomes {sorted(seen)} but final status {q['status']}")


async def scen_e(api, sc):
    seconds = float(os.environ.get("STRESS_SECONDS", "20"))
    w = await setup(api, sc, {f"u{i}": 1500 for i in range(10)}, operators=["u0"])
    m = Mixed(api, sc, w, seconds)
    await m.run()
    await m.final_checks()
    sc.notes.append(f"{m.ops} ops in {seconds:.0f}s, {len(m.reqs)} requests")


# -------------------------------------------------------------------- runner

SCENARIOS = [
    ("a  drain one wallet, 50 distinct keys", scen_a),
    ("b  same key x50 payment + key rules", scen_b),
    ("c1 50 pays on one request + replays", pay_race),
    ("c2 pay/decline/cancel races", terminal_race),
    ("d1 settlement semantics", scen_d1),
    ("d2 50 concurrent settlements", scen_d2),
    ("d3 same key x50 settlement", scen_d3),
    ("e  mixed load, 50 in flight", scen_e),
]


async def main():
    target = os.environ.get("TARGET_URL")
    if not target:
        print("TARGET_URL is required", file=sys.stderr)
        return 2
    seed = int(os.environ.get("STRESS_SEED", random.randrange(1 << 30)))
    api = Api(target.rstrip("/"))
    api.rng.seed(seed)
    random.seed(seed)
    print(f"target {target}  seed {seed}")
    rows = []
    for name, fn in SCENARIOS:
        sc = Scenario(name)
        marks = (len(api.five_xx), len(api.bad_envelope), len(api.transport))
        start = time.monotonic()
        try:
            await fn(api, sc)
        except Exception as exc:  # setup failure or a malformed response shape
            sc.check(False, f"aborted: {type(exc).__name__}: {exc}")
        for label, items, mark in (("5xx", api.five_xx, marks[0]),
                                   ("4xx without error envelope", api.bad_envelope, marks[1]),
                                   ("timeout or connection failure", api.transport, marks[2])):
            if len(items) > mark:
                sc.check(False, f"{len(items) - mark} x {label}, first: {items[mark]}")
        rows.append((sc, time.monotonic() - start))
        print(f"  {'PASS' if not sc.fail_count else 'FAIL'}  {name}", flush=True)
    await api.client.aclose()

    print("\nscenario                                 result  time   detail")
    for sc, took in rows:
        print(f"{sc.name:<40} {'PASS' if not sc.fail_count else 'FAIL':<7} {took:5.1f}s  {'; '.join(sc.notes)}")
        if sc.fail_count:
            for m in sc.fails:
                print(f"    - {m}")
            if sc.fail_count > len(sc.fails):
                print(f"    ... {sc.fail_count - len(sc.fails)} more")
    failed = sum(1 for sc, _ in rows if sc.fail_count)
    print(f"\n{api.count} requests, {len(api.five_xx)} 5xx, {len(api.bad_envelope)} bad error bodies, "
          f"{len(api.transport)} timeouts/failures; {len(rows) - failed}/{len(rows)} scenarios passed (seed {seed})")
    return 1 if failed or api.five_xx else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
