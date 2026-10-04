#!/usr/bin/env python3
"""Atomicity of correction batches under concurrent writes, with failure injected mid-batch (stage 4 gate).

    TARGET_URL=http://127.0.0.1:18300 python stage-4/tools/oracle/atomicity.py [--seed 1] [--concurrent 8] [--keep-going]

Black-box. Two phases, both judged by the reference model (model.py, D-62..D-75) and by direct all-or-none checks:

A. Failure injection. For every rule a batch can break, send a batch whose FIRST items are valid and whose LAST item breaks that rule
   (stale revision, unknown payment, capture, refund payment, refund_exceeds_payment, incomplete settlement, mismatched member instants,
   current unaffordable, historical overdraft, duplicate ids, future effective_at, 33 items, non-operator, no token, no key). The service must answer
   the exact code the spec's precedence gives and leave NOTHING changed: every payment's revision list, every wallet's total/available/held,
   every statement, a pre-taken snapshot's pages; and the rejected batch must not claim its idempotency key (the same key then commits a
   different valid batch).
B. Concurrency. 50 requests in flight over overlapping payments and settlements: batches, single corrections that share expected revisions with
   them, refunds, payments and duplicate-key replays. Afterwards: a rejected batch left no revision (reasons are unique tags), a committed batch left
   all of its revisions with one recorded_at and one correction_batch_id, per-payment revision chains are consecutive with strictly increasing
   recorded times, no two successes share an (expected revision), the whole committed history replays through the model in server-time order with
   every operation valid at its position (serialisable), wallets never negative at any boundary, sums of totals constant in every view.
Exit 0 only when nothing diverged.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff_run import Divergence, Run, fmt, fmtus  # noqa: E402
from model import UTC, parse  # noqa: E402

HOUR_AGO = timedelta(seconds=40)


class Atomicity(Run):
    # ------------------------------------------------------------------ building a populated, interesting state
    def pay(self, frm, to, amount, note="at"):
        status, resp = self.call("POST", "/payments", self.tokens[frm], {"to_handle": self.handles[to], "amount": amount, "note": note, "visibility": "public"}, self.key())
        assert status == 201, f"setup payment {frm}->{to} {amount}: {status} {resp}"
        self.model.add_payment(resp["payment_id"], frm, to, amount, self.see(resp["created_at"], "payment"), note=resp["note"], visibility=resp["visibility"])
        return resp["payment_id"]

    def settle(self, transfers):
        body = {"transfers": [{"from_handle": self.handles[f], "to_handle": self.handles[t], "amount": a} for f, t, a in transfers]}
        status, resp = self.call("POST", "/settlements", self.tokens["u_0"], body, self.key())
        assert status == 201, f"setup settlement: {status} {resp}"
        committed = self.see(resp["committed_at"], "settlement")
        ids = []
        for member, (f, t, a) in zip(resp["payments"], transfers):
            self.model.add_payment(member["payment_id"], f, t, a, committed, kind="settlement", note=member["note"], settlement=member["settlement_id"])
            ids.append(member["payment_id"])
        return resp["settlement_id"], ids

    def build_world(self):
        self.P = {}
        self.P["a"] = self.pay("u_1", "u_2", 100)
        self.P["b"] = self.pay("u_2", "u_1", 50)
        self.P["c"] = self.pay("u_0", "u_3", 300)
        self.P["d"] = self.pay("u_1", "u_4", 200)
        self.P["e"] = self.pay("u_2", "u_5", 150)
        self.P["f"] = self.pay("u_0", "u_1", 80)
        self.P["big"] = self.pay("u_1", "u_2", 200)
        self.S1, self.S1m = self.settle([("u_1", "u_2", 40), ("u_2", "u_3", 30), ("u_3", "u_1", 20)])
        self.S2, self.S2m = self.settle([("u_0", "u_4", 60), ("u_4", "u_5", 25)])
        # a capture: authorization u_2 -> u_1, final capture of 60
        status, auth = self.call("POST", "/authorizations", self.tokens["u_2"], {"to_handle": self.handles["u_1"], "amount": 100, "note": "hold"}, self.key())
        assert status == 201, f"setup authorization: {status} {auth}"
        self.model.add_auth(auth["authorization_id"], "u_2", "u_1", 100, self.see(auth["created_at"], "authorization"), parse(auth["expires_at"]))
        status, cap = self.call("POST", f"/authorizations/{auth['authorization_id']}/capture", self.tokens["u_1"], {"amount": 60}, self.key())
        assert status == 201, f"setup capture: {status} {cap}"
        self.model.add_payment(cap["payment_id"], "u_2", "u_1", 60, self.see(cap["created_at"], "capture"), kind="capture", note=cap["note"])
        self.model.add_capture(auth["authorization_id"], cap["payment_id"])
        self.sync_auths(["u_2"])
        self.P["cap"] = cap["payment_id"]
        # refunds: a small one on `a`, a large one on `big` (so a correction below it breaks refund_exceeds_payment)
        self.refund_ok(self.P["a"], "u_2", 30)
        self.refund_ok(self.P["big"], "u_2", 120)
        self.P["refund"] = next(p.id for p in self.model.payments.values() if p.kind == "refund")
        # historical overdraft: u_5 receives X, spends almost all of it, then receives Y: reversing X is affordable today but not at the time
        self.P["X"] = self.pay("u_3", "u_5", 400, "X")
        self.pay("u_5", "u_4", self.model.me("u_5", None, None, self.now())["available"] - 10, "spend")
        self.pay("u_0", "u_5", 500, "Y")
        time.sleep(2.2)          # effective times must be <= now: let the world age a little
        self.note("world built: payments, 2 settlements, a capture, 2 refunds, an overdraft trap")

    def refund_ok(self, pid, actor, amount):
        pay = self.model.payments[pid]
        status, resp = self.call("POST", f"/payments/{pid}/refunds", self.tokens[actor], {"amount": amount}, self.key())
        assert status == 201, f"setup refund: {status} {resp}"
        self.model.add_refund(resp["payment_id"], pid, amount, self.see(resp["created_at"], "refund"))

    # ------------------------------------------------------------------ full observable state
    def full_state(self):
        """Everything a reader could observe: revisions of every payment, wallets, statements, a frozen snapshot."""
        out = {"revisions": {}, "wallets": {}, "statements": {}}
        for pid, pay in self.model.payments.items():
            status, r = self.call("GET", f"/payments/{pid}/revisions", self.tokens[pay.frm])
            out["revisions"][pid] = [(x["revision"], x["amount"], x["effective_at"], x["recorded_at"], x["reason"], x.get("correction_batch_id")) for x in r["revisions"]] if status == 200 else status
        for u in self.users:
            st, me = self.call("GET", "/me", self.tokens[u])
            out["wallets"][u] = (me["total"], me["available"], me["held"]) if st == 200 else st
            st, stm = self.call("GET", "/statement", self.tokens[u], params={"limit": 200})
            out["statements"][u] = (stm["opening_balance"], stm["closing_balance"], [(e["payment"]["payment_id"], e["revision"], e["delta"], e["balance_after"], e["recorded_at"]) for e in stm["entries"]]) if st == 200 else st
        return out

    @staticmethod
    def diff_states(before, after):
        lines = []
        for part in ("revisions", "wallets", "statements"):
            for k in before[part]:
                if before[part][k] != after[part].get(k):
                    lines.append(f"  {part}[{k}]:\n    before {str(before[part][k])[:300]}\n    after  {str(after[part].get(k))[:300]}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ phase A: failure injection
    def item(self, pid, amount=None, eff=None, rev=None, reason="inj"):
        pay = self.model.payments[pid]
        return {"payment_id": pid, "expected_revision": len(pay.revs) if rev is None else rev,
                "amount": pay.current().amount if amount is None else amount,
                "effective_at": eff or parse(fmtus(self.now() - HOUR_AGO)), "reason": reason}

    def raw_body(self, items):
        return {"corrections": [{"payment_id": it["payment_id"], "expected_revision": it["expected_revision"], "amount": it["amount"],
                                 "effective_at": fmtus(it["effective_at"]) if not isinstance(it["effective_at"], str) else it["effective_at"],
                                 "reason": it["reason"]} for it in items]}

    def inject(self, name, items, want_code, token="u_0", body=None, use_key=True):
        """Send a batch that must fail with `want_code` (the spec's precedence) and change nothing."""
        model_says = (self.model.batch_outcomes(items, self.now())
                      if body is None and token == "u_0" and not any(isinstance(i["effective_at"], str) for i in items) else None)
        if model_says is not None:
            self.expect(model_says == {want_code}, f"[{name}] the reference model disagrees with the expected code {want_code}", f"model says {sorted(model_says)}")
        snap = None
        token_of = self.tokens.get(token) if token else None
        before = self.full_state()
        user, snap_token = "u_1", None
        status, stm = self.call("GET", "/statement", self.tokens[user], params={"limit": 200})
        if status == 200:
            snap_token, snap_pages = stm.get("snapshot"), self.shape(stm)
        key = self.key() if use_key else None
        sent = body if body is not None else self.raw_body(items)
        status, resp = self.call("POST", "/correction-batches", token_of, sent, key)
        code = "ok" if status == 201 else (str(status) if status in (401, 403, 404) else ((resp or {}).get("error") or {}).get("code") if isinstance(resp, dict) else None)
        self.outcomes[f"inject:{name}:{code}"] = 1
        self.note(f"INJECT {name}: expected {want_code}, got {status} {code}")
        self.expect(code == want_code, f"[{name}] a batch whose last item breaks the rule must answer {want_code}", f"got {status} {resp}; body {json.dumps(sent)[:400]}")
        after = self.full_state()
        self.expect(before == after, f"[{name}] a rejected batch must change nothing (revisions, wallets, statements)", self.diff_states(before, after))
        if snap_token:
            st, page = self.call("GET", "/statement", self.tokens[user], params={"snapshot": snap_token, "limit": 200})
            self.expect(st == 200 and self.shape(page) == snap_pages, f"[{name}] a snapshot taken before a rejected batch must still page identically", f"{st}")
        return key

    def phase_a(self):
        P, S1m, S2m, model = self.P, self.S1m, self.S2m, self.model
        eff = parse(fmtus(self.now() - HOUR_AGO))
        a, b, c = self.item(P["a"], 90, eff), self.item(P["b"], 40, eff), self.item(P["f"], 70, eff)
        valid = [a, b]

        keys = {}
        keys["stale"] = self.inject("stale", valid + [self.item(P["c"], 0, eff, rev=len(model.payments[P["c"]].revs) + 5)], "stale_revision")
        self.inject("unknown", valid + [{"payment_id": "p_nope", "expected_revision": 1, "amount": 0, "effective_at": eff, "reason": "x"}], "404")
        self.inject("capture", valid + [self.item(P["cap"], 0, eff)], "linked_payment_immutable")
        self.inject("refund_payment", valid + [self.item(P["refund"], 0, eff)], "linked_payment_immutable")
        self.inject("refund_exceeds", valid + [self.item(P["big"], 100, eff)], "refund_exceeds_payment")     # 120 already refunded
        self.inject("incomplete_settlement", valid + [self.item(S1m[0], 0, eff)], "incomplete_settlement")
        self.inject("incomplete_settlement_2", valid + [self.item(m, 0, eff) for m in S1m[:2]], "incomplete_settlement")
        mismatch = [self.item(S1m[0], 0, eff), self.item(S1m[1], 0, eff), self.item(S1m[2], 0, eff + timedelta(seconds=1))]
        self.inject("mismatched_member_instants", valid + mismatch, "validation_failed")
        # the first erroneous item decides, even if a later item has a different defect
        self.inject("first_item_error_wins", [self.item(P["c"], 0, eff, rev=9), self.item(P["cap"], 0, eff)], "stale_revision")
        self.inject("item_beats_settlement", [self.item(S1m[0], 0, eff), self.item(P["f"], 0, eff, rev=7)], "stale_revision")
        # current unaffordable: raise a payment far beyond its sender's available funds
        self.inject("insufficient_funds", valid + [self.item(P["e"], 10 ** 7, eff)], "insufficient_funds")
        # historical overdraft: reversing X leaves u_5 negative when it spent the money (but today's balance can cover it)
        self.inject("historical_overdraft", valid + [self.item(P["X"], 0, parse(fmtus(model.payments[P["X"]].created_at)))], "historical_overdraft")
        # combined net matters: A alone is unaffordable, but with B (a credit to the same wallet) the batch is fine, so a batch
        # that is unaffordable ONLY because of its last item leaves the earlier items out too
        self.inject("duplicate_ids", [a, a], "validation_failed")
        self.inject("future_effective_at", valid + [dict(self.item(P["f"], 70, eff), effective_at=fmt(self.now() + timedelta(seconds=60)))], "validation_failed")
        many = [self.item(P["f"], 70, eff)] * 33
        self.inject("33_items", [], "validation_failed", body=self.raw_body(many))
        self.inject("empty", [], "validation_failed", body={"corrections": []})
        self.inject("non_operator", valid, "403", token="u_1")
        self.inject("no_token", valid, "401", token=None)
        status, resp = self.call("POST", "/correction-batches", self.tokens["u_0"], self.raw_body(valid))
        self.expect(status == 400 and resp["error"]["code"] == "missing_idempotency_key", "a batch needs an Idempotency-Key", f"{status} {resp}")
        # a rejected batch claims no key: the same key now commits a different, valid batch
        key = keys["stale"]
        good = [self.item(P["f"], 75, eff, reason="inj.0")]
        status, resp = self.call("POST", "/correction-batches", self.tokens["u_0"], self.raw_body(good), key)
        self.expect(status == 201, "a key used by a REJECTED batch is free: the same key must commit a different valid batch (idempotency)", f"{status} {resp}")
        if status == 201:
            self.check_batch_receipt(good, "inj", self.raw_body(good), key, resp)

    def refund_uses_available_funds(self):
        """A refund comes from the receiver's AVAILABLE funds: with money held, an amount between available and total is refused."""
        model = self.model
        total = model.me("u_5", None, None, self.now())["total"]
        if total < 10:
            return
        hold = total - 5
        status, auth = self.call("POST", "/authorizations", self.tokens["u_5"], {"to_handle": self.handles["u_1"], "amount": hold, "note": "freeze"}, self.key())
        if status != 201:
            return
        model.add_auth(auth["authorization_id"], "u_5", "u_1", hold, self.see(auth["created_at"], "authorization"), parse(auth["expires_at"]))
        before = self.full_state()
        pid = self.P["e"]                                        # u_2 -> u_5 150: u_5 is the receiver and may refund
        want = model.refund_outcomes(pid, "u_5", 100, self.now())
        status, resp = self.call("POST", f"/payments/{pid}/refunds", self.tokens["u_5"], {"amount": 100}, self.key())
        code = "ok" if status == 201 else ((resp or {}).get("error") or {}).get("code")
        self.expect(code in want and code == "insufficient_funds", "a refund must come from AVAILABLE funds (total minus holds): refused with insufficient_funds", f"u_5 total {total}, held {hold}: {status} {resp}")
        self.expect(before == self.full_state(), "a refused refund must change nothing", "")
        status, resp = self.call("POST", f"/authorizations/{auth['authorization_id']}/void", self.tokens["u_5"])
        if status == 200:
            self.see(resp["closed_at"], "void")
            model.close_auth(auth["authorization_id"], "voided", parse(resp["closed_at"]))

    # ------------------------------------------------------------------ phase R: batches and singles sharing one expected revision
    def phase_race(self, rounds=3):
        """"Concurrent corrections sharing any expected payment revision cannot both succeed": a burst of batches and single corrections that all
        name the same (payment, expected revision) must produce at most one winner (exactly one when any of them is valid)."""
        P, model = self.P, self.model
        for rnd in range(rounds):
            pid = [P["a"], P["d"], P["f"]][rnd % 3]
            other = P["e"]
            pay = model.payments[pid]
            n = len(pay.revs)
            eff = fmtus(self.now() - timedelta(seconds=20))
            cur = pay.current().amount
            amounts = [max(cur - 1 - (i % 3), 0) for i in range(16)]

            def go(i):
                tag = f"R{self.seed}.{rnd}.{i}"
                if i % 2 == 0:
                    corr = [{"payment_id": pid, "expected_revision": n, "amount": amounts[i], "effective_at": eff, "reason": tag + ".0"}]
                    if i % 4 == 0:
                        corr.append({"payment_id": other, "expected_revision": len(model.payments[other].revs), "amount": model.payments[other].current().amount,
                                     "effective_at": eff, "reason": tag + ".1"})
                    return "batch", tag, self.call("POST", "/correction-batches", self.tokens["u_0"], {"corrections": corr}, self.key())
                body = {"expected_revision": n, "amount": amounts[i], "effective_at": eff, "reason": tag}
                return "single", tag, self.call("POST", f"/payments/{pid}/corrections", self.tokens[pay.frm], body, self.key())

            with ThreadPoolExecutor(16) as pool:
                results = list(pool.map(go, range(16)))
            wins = [(k, t, r) for k, t, (st, r) in results if st in (200, 201)]
            self.note(f"race round {rnd}: {len(wins)} of 16 succeeded on {pid} (expected_revision {n})")
            self.expect(len(wins) <= 1, "concurrent corrections sharing an expected revision: more than one succeeded", f"{pid}: {[(k, t) for k, t, _ in wins]}")
            for st, r in [x[2] for x in results]:
                if st not in (200, 201):
                    self.expect(r["error"]["code"] in ("stale_revision", "insufficient_funds", "historical_overdraft", "refund_exceeds_payment"), "race loser answered unexpectedly", f"{st} {r}")
            for kind, tag, (st, r) in results:
                if st == 201 and kind == "batch":
                    revs = r["revisions"]
                    for rv in revs:
                        model.add_revision(rv["payment_id"], rv["revision"], rv["amount"], parse(rv["effective_at"]), parse(r["recorded_at"]), rv["reason"], r["correction_batch_id"])
                elif st == 201:
                    model.add_revision(pid, r["revision"], r["amount"], parse(r["effective_at"]), parse(r["recorded_at"]), r["reason"])
            time.sleep(0.2)

    # ------------------------------------------------------------------ phase B: concurrency
    def phase_b(self, seconds):
        time.sleep(1.2)
        P, model = self.P, self.model
        targets = [P[k] for k in ("a", "b", "c", "d", "e", "f", "big")]
        groups = [self.S1m, self.S2m]
        log, lock = [], threading.Lock()
        stop = time.time() + seconds
        counter = [0]

        def revs_now(pid):
            st, r = self.call("GET", f"/payments/{pid}/revisions", self.tokens[model.payments[pid].frm])
            return len(r["revisions"]) if st == 200 else 1

        def new_tag(kind):
            with lock:
                counter[0] += 1
                return f"{kind}{counter[0]}"

        def eff_for(rng):
            return fmtus(self.now() - timedelta(seconds=rng.randrange(3, 40), microseconds=rng.randrange(1000)))

        def record(kind, req, status, resp, extra=None):
            with lock:
                log.append({"kind": kind, "req": req, "status": status, "resp": resp, **(extra or {})})

        def worker(w):
            rng = random.Random(self.seed * 100 + w)
            while time.time() < stop:
                try:
                    r = rng.random()
                    if r < 0.28:        # batch over overlapping payments, sometimes a whole settlement
                        pids = rng.sample(targets, rng.choice([1, 2, 3]))
                        items = [(pid, rng.choice([0, 1, 5, 40, 90]), None) for pid in pids]
                        if rng.random() < 0.5:
                            grp = rng.choice(groups)
                            e = eff_for(rng)
                            items += [(pid, rng.choice([0, 3, 9]), e) for pid in grp]
                        tag = new_tag("B")
                        corr = []
                        for i, (pid, amount, e) in enumerate(items):
                            corr.append({"payment_id": pid, "expected_revision": revs_now(pid), "amount": amount, "effective_at": e or eff_for(rng), "reason": f"{tag}.{i}"})
                        body = {"corrections": corr}
                        key = self.key()
                        s, resp = self.call("POST", "/correction-batches", self.tokens["u_0"], body, key)
                        record("batch", body, s, resp, {"tag": tag, "key": key})
                        if s == 201 and rng.random() < 0.3:       # a concurrent duplicate of a committed batch
                            s2, resp2 = self.call("POST", "/correction-batches", self.tokens["u_0"], body, key)
                            record("batch_replay", body, s2, resp2, {"tag": tag, "original": resp})
                    elif r < 0.55:      # single correction racing the batches on the same expected revision
                        pid = rng.choice(targets)
                        pay = model.payments[pid]
                        tag = new_tag("C")
                        body = {"expected_revision": revs_now(pid), "amount": rng.choice([0, 1, 5, 40, 90]), "effective_at": eff_for(rng), "reason": tag}
                        s, resp = self.call("POST", f"/payments/{pid}/corrections", self.tokens[pay.frm], body, self.key())
                        record("single", {"pid": pid, **body}, s, resp, {"tag": tag})
                    elif r < 0.75:      # refunds
                        pid = rng.choice(targets)
                        pay = model.payments[pid]
                        s, resp = self.call("POST", f"/payments/{pid}/refunds", self.tokens[pay.to], {"amount": rng.choice([1, 3, 10])}, self.key())
                        record("refund", {"pid": pid}, s, resp)
                    else:
                        frm, to = rng.sample(self.users, 2)
                        s, resp = self.call("POST", "/payments", self.tokens[frm], {"to_handle": self.handles[to], "amount": rng.choice([1, 2, 5]), "note": "c"}, self.key())
                        record("payment", {"frm": frm, "to": to}, s, resp)
                except Exception as exc:  # noqa: BLE001
                    record("error", {}, 0, repr(exc))

        with ThreadPoolExecutor(50) as pool:
            for f in [pool.submit(worker, w) for w in range(50)]:
                f.result()
        self.check_concurrent(log, targets)

    def check_concurrent(self, log, targets):
        model = self.model
        bad_5xx = [e for e in log if e["status"] >= 500 or e["status"] == 0]
        for e in bad_5xx[:3]:
            self.diverge("a request failed or answered 5xx under concurrency", f"{e['kind']} {e['status']} {str(e['resp'])[:200]}")
        counts = {}
        for e in log:
            counts[(e["kind"], e["status"])] = counts.get((e["kind"], e["status"]), 0) + 1
        self.note("concurrent outcomes: " + ", ".join(f"{k[0]}:{k[1]}x{v}" for k, v in sorted(counts.items())))
        # 1. read every payment's revisions once
        histories = {}
        for pid in list(model.payments):
            st, r = self.call("GET", f"/payments/{pid}/revisions", self.tokens[model.payments[pid].frm])
            if st == 200:
                histories[pid] = r["revisions"]
        by_reason = {}
        for pid, revs in histories.items():
            for r in revs[1:]:
                by_reason.setdefault(r["reason"], []).append((pid, r))
        # 2. committed batches: all revisions present, one recorded_at, one batch id; rejected batches left nothing
        ops = []
        for e in log:
            if e["kind"] == "batch":
                if e["status"] == 201:
                    resp = e["resp"]
                    revs = resp["revisions"]
                    for i, r in enumerate(revs):
                        found = by_reason.get(f"{e['tag']}.{i}", [])
                        self.expect(len(found) == 1 and found[0][0] == r["payment_id"] and found[0][1]["revision"] == r["revision"]
                                    and found[0][1]["recorded_at"] == resp["recorded_at"] and found[0][1].get("correction_batch_id") == resp["correction_batch_id"],
                                    "a committed batch must leave every revision, with its recorded_at and correction_batch_id", f"{e['tag']}.{i}: receipt {r}; history {found}")
                    self.expect(len({r["recorded_at"] for r in revs}) == 1, "one recorded_at per batch", e["tag"])
                    ops.append((parse(resp["recorded_at"]), "batch", e))
                else:
                    leaked = [(k, v) for k, v in by_reason.items() if k.startswith(e["tag"] + ".")]
                    self.expect(not leaked, "a REJECTED batch left revisions behind (partial effect)", f"{e['tag']} answered {e['status']} {str(e['resp'])[:150]}; leaked {leaked}")
                    if e["status"] == 409 or e["status"] == 422:
                        code = e["resp"]["error"]["code"]
                        self.expect(code in ("stale_revision", "insufficient_funds", "historical_overdraft", "refund_exceeds_payment", "validation_failed", "incomplete_settlement",
                                             "linked_payment_immutable"), "unexpected batch rejection under load", f"{e['status']} {e['resp']}")
            elif e["kind"] == "batch_replay":
                self.expect(e["status"] == 200 and e["resp"] == e["original"], "a concurrent replay of a committed batch must return 200 and the original response", f"{e['status']}")
            elif e["kind"] == "single":
                found = by_reason.get(e["tag"], [])
                if e["status"] == 201:
                    self.expect(len(found) == 1 and found[0][0] == e["req"]["pid"], "a committed correction must be in the history exactly once", f"{e['tag']}: {found}")
                    ops.append((parse(e["resp"]["recorded_at"]), "single", e))
                else:
                    self.expect(not found, "a rejected correction left a revision behind", f"{e['tag']}: {e['status']} {str(e['resp'])[:120]} / {found}")
            elif e["kind"] == "refund" and e["status"] == 201:
                ops.append((parse(e["resp"]["created_at"]), "refund", e))
            elif e["kind"] == "payment" and e["status"] == 201:
                ops.append((parse(e["resp"]["created_at"]), "payment", e))
        # 3. per-payment chains: consecutive, strictly increasing recorded_at, no two successes on one expected revision
        for pid, revs in histories.items():
            self.expect([r["revision"] for r in revs] == list(range(1, len(revs) + 1)), "revision numbers must be consecutive (two successes shared an expected revision?)", f"{pid}: {[r['revision'] for r in revs]}")
            stamps = [parse(r["recorded_at"]) for r in revs]
            self.expect(all(x < y for x, y in zip(stamps, stamps[1:])), "recorded times of one payment must strictly increase", f"{pid}")
        # 4. serialisability: replay committed operations in server-time order through the model; each must be valid at its position
        ops.sort(key=lambda o: o[0])
        for when, kind, e in ops:
            if kind == "payment":
                r = e["resp"]
                self.expect(model.me(e["req"]["frm"], None, None, when)["available"] >= r["amount"], "a committed payment was unaffordable at its position in the serial order", f"{r['payment_id']}")
                model.add_payment(r["payment_id"], e["req"]["frm"], e["req"]["to"], r["amount"], when, note=r["note"], visibility=r["visibility"])
            elif kind == "refund":
                r = e["resp"]
                want = model.refund_outcomes(e["req"]["pid"], model.payments[e["req"]["pid"]].to, r["amount"], when)
                self.expect("ok" in want, "a committed refund was not valid at its position in the serial order", f"{r['payment_id']}: model says {sorted(want)}")
                model.add_refund(r["payment_id"], e["req"]["pid"], r["amount"], when)
            elif kind == "single":
                r, q = e["resp"], e["req"]
                pay = model.payments[q["pid"]]
                want = model.correction_outcomes(q["pid"], pay.frm, q["expected_revision"], q["amount"], parse(q["effective_at"]), when)
                self.expect("ok" in want and r["revision"] == len(pay.revs) + 1, "a committed correction was not valid at its position in the serial order (lost update?)",
                            f"{q['pid']} expected_revision {q['expected_revision']} vs {len(pay.revs)} at that point; model {sorted(want)}")
                model.add_revision(q["pid"], r["revision"], q["amount"], parse(q["effective_at"]), when, q["reason"])
            else:
                body, resp = e["req"], e["resp"]
                items = [{"payment_id": c["payment_id"], "expected_revision": c["expected_revision"], "amount": c["amount"], "effective_at": parse(c["effective_at"])} for c in body["corrections"]]
                want = model.batch_outcomes(items, when)
                self.expect("ok" in want, "a committed batch was not valid at its position in the serial order (partial or lost update?)", f"{e['tag']}: model says {sorted(want)}")
                if "ok" in want:
                    model.apply_batch(items, when, resp["correction_batch_id"], [c["reason"] for c in body["corrections"]])
        # 5. the final state: conserved sums, no negative wallet at any boundary, every view equals the model
        self.all_nonnegative()
        self.grid(30)

    # ------------------------------------------------------------------ run
    def run_all(self, seconds):
        self.setup()
        self.build_world()
        self.phase_a()
        self.refund_uses_available_funds()
        self.phase_race()
        if seconds:
            self.phase_b(seconds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=int(os.environ.get("DIFF_SEED", random.randrange(1 << 30))))
    ap.add_argument("--concurrent", type=float, default=8, help="seconds of the concurrent phase (0 = failure injection only)")
    ap.add_argument("--keep-going", action="store_true")
    args = ap.parse_args()
    base = os.environ.get("TARGET_URL")
    if not base:
        print("TARGET_URL is required", file=sys.stderr)
        return 2
    run = Atomicity(base, args.seed, args.keep_going)
    run.protocol = False          # shape/protocol checks belong to diff_run.py
    run.seed_closed = False
    began = time.time()
    try:
        run.run_all(args.concurrent)
    except Divergence as d:
        print(str(d))
    except AssertionError as exc:
        print(f"SETUP FAILED: {exc}")
        return 2
    run.http.close()
    for text in (run.findings if args.keep_going else run.findings[1:]):
        print("\n" + (text if args.keep_going and text is run.findings[0] else text.split("-- operations")[0]))
    for line in run.log:
        if "concurrent outcomes" in line:
            print(line)
    inject = sorted(k for k in run.outcomes if k.startswith("inject:"))
    print(f"\nfailure injection: {len(inject)} rules exercised; {run.queries} historical reads; {time.time() - began:.0f}s; seed {args.seed}: "
          f"{'FAIL (' + str(len(run.findings)) + ' divergences)' if run.findings else 'PASS no divergence'}")
    return 1 if run.findings else 0


if __name__ == "__main__":
    sys.exit(main())
