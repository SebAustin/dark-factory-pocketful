#!/usr/bin/env python3
"""S2.6: concurrency and load for holds (stdlib only).

    TARGET_URL=http://127.0.0.1:18210 HOLDS_SECONDS=30 python3 stage-2/tools/holds_stress.py

50 workers, each on its own keep-alive connection, mix payments, authorizations, captures
(partial, final, non-final), voids, requests + pay, settlements and reads, with a 3 s hold
lifetime so holds also expire under load. Checks the stage 2 invariants:
- during load, at every sampled GET /me: available >= 0, held >= 0, balance == total,
  available == total - held;
- at the end (quiescent): sum of totals == seeded total; for every user,
  total == seed + incoming - outgoing over the payments in its own feed; held == sum of
  remaining_amount of its open outgoing holds; every hold has captured <= amount,
  remaining == 0 unless open, captured == sum of its capture payments, payment_ids match;
- no 5xx, no response slower than 5 s, every 4xx carries the error envelope.
Exit 0 = pass.
"""
import http.client
import json
import os
import random
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

TARGET = urlsplit(os.environ.get("TARGET_URL", "http://127.0.0.1:18210"))
SECONDS = float(os.environ.get("HOLDS_SECONDS", "30"))
WORKERS = 50
USERS = 12
SEED = 20000
TTL = 3
LIMIT_S = 5.0
PW = "correct horse"

guard = threading.Lock()
problems, latencies, statuses = [], [], {}
local = threading.local()


def problem(text):
    with guard:
        problems.append(text)


def call(method, path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    for attempt in (1, 2):
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = local.conn = http.client.HTTPConnection(TARGET.hostname, TARGET.port,
                                                           timeout=12)
        started = time.monotonic()
        try:
            conn.request(method, path, None if body is None else json.dumps(body), headers)
            r = conn.getresponse()
            raw = r.read()
            break
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            local.conn = None
            if attempt == 2 or method != "GET":
                problem("transport {} {} {!r}".format(method, path, exc))
                return 0, None
    took = time.monotonic() - started
    data = json.loads(raw) if raw else None
    with guard:
        latencies.append(took)
        statuses[r.status] = statuses.get(r.status, 0) + 1
    if r.status >= 500:
        problem("5xx {} {} {}".format(method, path, raw[:200]))
    elif r.status >= 400 and not (isinstance(data, dict) and "code" in data.get("error", {})):
        problem("4xx without envelope {} {}".format(method, path))
    if took > LIMIT_S:
        problem("slow {:.2f}s {} {}".format(took, method, path))
    return r.status, data


def setup():
    users = [{"id": "u%d" % i, "email": "u%d@e.com" % i, "password": PW,
              "display_name": "U%d" % i, "handle": "u%d" % i, "balance": SEED}
             for i in range(USERS)]
    status, _ = call("POST", "/_test/reset", {
        "currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": TTL,
        "users": users, "settlement_operator_ids": ["u0"]})
    assert status == 204, status
    return [call("POST", "/auth/login", {"email": "u%d@e.com" % i, "password": PW})[1]["token"]
            for i in range(USERS)]


class Load:
    def __init__(self, tokens):
        self.tok = tokens
        self.holds = []      # (authorization_id, payer index, receiver index)
        self.requests = []   # (request_id, requester index, payer index)
        self.ops = 0

    def worker(self, deadline):
        rng = random.Random()
        while time.monotonic() < deadline:
            a, b = rng.sample(range(USERS), 2)
            op = rng.random()
            with guard:
                self.ops += 1
            if op < 0.18:
                call("POST", "/payments", {"to_handle": "u%d" % b,
                                           "amount": rng.randint(1, 3000),
                                           "visibility": rng.choice(["public", "private"])},
                     self.tok[a], uuid.uuid4().hex)
            elif op < 0.38:
                s, body = call("POST", "/authorizations",
                               {"to_handle": "u%d" % b, "amount": rng.randint(1, 4000)},
                               self.tok[a], uuid.uuid4().hex)
                if s == 201:
                    with guard:
                        self.holds.append((body["authorization_id"], a, b))
            elif op < 0.58 and self.holds:
                aid, payer, receiver = rng.choice(self.holds)
                body = rng.choice([{}, {"amount": rng.randint(1, 1500)},
                                   {"amount": rng.randint(1, 1500), "final": False},
                                   {"final": False}])
                k = uuid.uuid4().hex
                s1, first = call("POST", "/authorizations/%s/capture" % aid, body,
                                 self.tok[receiver], k)
                if s1 == 201 and rng.random() < 0.3:
                    s2, again = call("POST", "/authorizations/%s/capture" % aid, body,
                                     self.tok[receiver], k)
                    if (s2, again) != (200, first):
                        problem("capture replay {} != 200 original".format(s2))
            elif op < 0.66 and self.holds:
                aid, payer, receiver = rng.choice(self.holds)
                call("POST", "/authorizations/%s/void" % aid, None, self.tok[payer])
            elif op < 0.74:
                s, body = call("POST", "/requests", {"payer_handle": "u%d" % b,
                                                     "amount": rng.randint(1, 2000)},
                               self.tok[a], uuid.uuid4().hex)
                if s == 201:
                    with guard:
                        self.requests.append((body["request_id"], a, b))
            elif op < 0.80 and self.requests:
                rid, requester, payer = rng.choice(self.requests)
                call("POST", "/requests/%s/pay" % rid, {}, self.tok[payer], uuid.uuid4().hex)
            elif op < 0.85:
                others = rng.sample(range(USERS), 4)
                call("POST", "/settlements", {"transfers": [
                    {"from_handle": "u%d" % others[0], "to_handle": "u%d" % others[1],
                     "amount": rng.randint(1, 5000)},
                    {"from_handle": "u%d" % others[2], "to_handle": "u%d" % others[3],
                     "amount": rng.randint(1, 5000)}]}, self.tok[0], uuid.uuid4().hex)
            elif op < 0.92:
                call("GET", "/authorizations?limit=20", token=self.tok[a])
            else:
                self.sample(a)

    def sample(self, i):
        s, me = call("GET", "/me", token=self.tok[i])
        if s != 200:
            return
        if me["available"] < 0 or me["held"] < 0 or me["balance"] != me["total"] \
                or me["available"] != me["total"] - me["held"]:
            problem("bad /me read: {}".format(me))


def all_pages(path, token, key):
    items, offset = [], 0
    while True:
        s, body = call("GET", "{}{}limit=200&offset={}".format(
            path, "&" if "?" in path else "?", offset), token=token)
        items += body[key]
        if not body["has_more"]:
            return items
        offset += 200


def final_checks(tokens):
    time.sleep(TTL + 1)  # let the clock expire whatever is still open, then read once
    totals = {}
    for i, tok in enumerate(tokens):
        me = call("GET", "/me", token=tok)[1]
        totals[i] = me
        feed = all_pages("/activity", tok, "payments")
        mine = [p for p in feed if p["from_user_id"] == "u%d" % i or p["to_user_id"] == "u%d" % i]
        net = sum(p["amount"] if p["to_user_id"] == "u%d" % i else -p["amount"] for p in mine)
        if me["total"] != SEED + net:
            problem("u{} total {} != seed + feed net {}".format(i, me["total"], SEED + net))
        holds = all_pages("/authorizations?direction=outgoing", tok, "authorizations")
        open_rest = sum(a["remaining_amount"] for a in holds if a["status"] == "open")
        if me["held"] != open_rest:
            problem("u{} held {} != open remaining {}".format(i, me["held"], open_rest))
        by_id = {p["payment_id"]: p for p in feed}
        for a in holds:
            if a["captured_amount"] > a["amount"] or (a["status"] != "open"
                                                      and a["remaining_amount"] != 0):
                problem("hold {} breaks captured/remaining: {}".format(a["authorization_id"], a))
            caps = [by_id[pid] for pid in a["payment_ids"] if pid in by_id]
            if len(caps) != len(a["payment_ids"]) or sum(p["amount"] for p in caps) != a[
                    "captured_amount"] or any(p["authorization_id"] != a["authorization_id"]
                                              for p in caps):
                problem("hold {} captures do not add up".format(a["authorization_id"]))
    total = sum(m["total"] for m in totals.values())
    if total != SEED * USERS:
        problem("sum of totals {} != seeded {}".format(total, SEED * USERS))
    return sum(m["held"] for m in totals.values())


def main():
    tokens = setup()
    load = Load(tokens)
    deadline = time.monotonic() + SECONDS
    threads = [threading.Thread(target=load.worker, args=(deadline,)) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    held_after = final_checks(tokens)
    ordered = sorted(latencies)
    print("{} ops, {} requests, {} holds, p50 {:.3f}s p99 {:.3f}s max {:.3f}s, statuses {}, "
          "held after expiry {}".format(load.ops, len(ordered), len(load.holds),
                                        ordered[len(ordered) // 2],
                                        ordered[int(len(ordered) * 0.99)], ordered[-1],
                                        dict(sorted(statuses.items())), held_after))
    for p in problems[:15]:
        print("FAIL", p)
    print("PASS" if not problems else "FAIL ({} problems)".format(len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
