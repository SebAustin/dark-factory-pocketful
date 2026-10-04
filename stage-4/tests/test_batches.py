"""S4.2: correction batches (stage 4; D-66..D-70)."""
import copy
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from harness import FIXTURE, call, reset
from test_payments import token
from test_statement import statement

BATCH_REV_KEYS = ["payment_id", "revision", "amount", "effective_at", "recorded_at", "reason",
                  "correction_batch_id"]


def key():
    return uuid.uuid4().hex


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="microseconds")


def me(tok, **params):
    q = "&".join("{}={}".format(k, quote(v, safe="")) for k, v in params.items())
    return call("GET", "/me" + ("?" + q if q else ""), token=tok).body


def item(pid, amount, expected=1, eff=None, reason="batch fix", **extra):
    return {"payment_id": pid, "expected_revision": expected, "amount": amount,
            "effective_at": eff or ago(0.5), "reason": reason, **extra}


class Base(unittest.TestCase):
    def setUp(self):
        f = copy.deepcopy(FIXTURE)
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))
        self.p1 = self.pay(self.ada, "bob", 1000)
        self.p2 = self.pay(self.bob, "ada", 400)
        st = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 100},
            {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}, token=self.cy,
            key=key()).body
        self.members = [p["payment_id"] for p in st["payments"]]
        self.settlement = st

    def pay(self, tok, to, amount):
        return call("POST", "/payments", {"to_handle": to, "amount": amount}, token=tok,
                    key=key()).body["payment_id"]

    def batch(self, items, tok=None, k=None, raw=None):
        return call("POST", "/correction-batches",
                    None if raw is not None else {"corrections": items},
                    token=tok or self.cy, key=k or key(), raw=raw)


class SuccessTest(Base):
    def test_201_shape_shared_recorded_at_and_money(self):
        eff = ago(0.5)
        r = self.batch([item(self.p1, 600, eff=eff), item(self.p2, 500, eff=eff)])
        self.assertEqual(r.status, 201, r.raw)
        b = r.body
        self.assertEqual(list(b), ["correction_batch_id", "recorded_at", "revisions"])
        self.assertEqual([x["payment_id"] for x in b["revisions"]], [self.p1, self.p2])
        for rev in b["revisions"]:
            self.assertEqual(list(rev), BATCH_REV_KEYS)
            self.assertEqual((rev["recorded_at"], rev["correction_batch_id"], rev["revision"]),
                             (b["recorded_at"], b["correction_batch_id"], 2))
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]),
                         (10000 - 600 + 500 - 100, 2500 + 600 - 500 + 100 - 50))
        revs = call("GET", "/payments/%s/revisions" % self.p1, token=self.ada).body["revisions"]
        self.assertEqual(revs[-1]["correction_batch_id"], b["correction_batch_id"])
        entry = [e for e in statement(self.ada).body["entries"]
                 if e["payment"]["payment_id"] == self.p1][0]
        self.assertEqual((entry["revision"], entry["correction_batch_id"]),
                         (2, b["correction_batch_id"]))

    def test_whole_settlement_with_offset_spellings(self):
        t = datetime.now(timezone.utc) - timedelta(hours=1)
        utc = t.isoformat(timespec="microseconds")
        east = t.astimezone(timezone(timedelta(hours=2))).isoformat(timespec="microseconds")
        before = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 100},
            {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}, token=self.cy,
            key="settle-replay").body
        members = [p["payment_id"] for p in before["payments"]]
        r = self.batch([item(members[0], 0, eff=utc), item(members[1], 0, eff=east)])
        self.assertEqual(r.status, 201, r.raw)
        again = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 100},
            {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}, token=self.cy,
            key="settle-replay")
        self.assertEqual((again.status, again.body), (200, before))  # receipt unchanged
        single = call("POST", "/payments/%s/corrections" % members[0],
                      {"expected_revision": 2, "amount": 1, "effective_at": utc,
                       "reason": "x"}, token=self.ada, key=key())
        self.assertEqual(single.code, "linked_payment_immutable")  # single path still refuses

    def test_affordable_only_together(self):
        # bob has 3150; raising p2 by 5000 debits bob, raising p1 by 3000 credits bob.
        r = self.batch([item(self.p2, 400 + 5000)])
        self.assertEqual(r.code, "insufficient_funds")
        ok = self.batch([item(self.p1, 1000 + 3000), item(self.p2, 400 + 5000)])
        self.assertEqual(ok.status, 201, ok.raw)

    def test_replay_and_unknown_fields(self):
        k = key()
        items = [item(self.p1, 900, note="ignored")]
        first = self.batch(items, k=k)
        again = self.batch(items, k=k)
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(first.body, again.body)
        self.assertEqual(self.batch([item(self.p1, 901)], k=k).code, "idempotency_key_reuse")
        r = call("POST", "/correction-batches", {"corrections": [item(self.p1, 800, expected=2)],
                                                 "extra": 1}, token=self.cy, key=key())
        self.assertEqual(r.status, 201)

    def test_old_snapshot_unchanged_and_new_statement_reflects(self):
        first = statement(self.ada).body
        self.assertEqual(self.batch([item(self.p1, 1)]).status, 201)
        again = statement(self.ada, snapshot=first["snapshot"]).body
        self.assertEqual(again, first)
        self.assertNotEqual(statement(self.ada).body["entries"], first["entries"])


class ErrorTest(Base):
    def test_access(self):
        self.assertEqual(self.batch([item(self.p1, 1)], tok=self.ada).code, "forbidden")
        r = call("POST", "/correction-batches", {"corrections": [item(self.p1, 1)]}, key=key())
        self.assertEqual(r.status, 401)
        r = self.batch(None, tok=self.ada, raw="{bad")
        self.assertEqual(r.code, "forbidden")  # 403 before the body (D-66)
        self.assertEqual(self.batch(None, raw="{bad").code, "malformed_request")
        r = call("POST", "/correction-batches", {"corrections": [item(self.p1, 1)]},
                 token=self.cy)
        self.assertEqual(r.code, "missing_idempotency_key")

    def test_shape(self):
        for body in ({}, {"corrections": "x"}, {"corrections": []},
                     {"corrections": [item(self.p1, 1)] * 1 + [item(self.p1, 2)]},
                     {"corrections": [5]},
                     {"corrections": [dict(item(self.p1, 1), payment_id=7)]},
                     {"corrections": [item("p_%d" % i, 1) for i in range(33)]}):
            r = call("POST", "/correction-batches", body, token=self.cy, key=key())
            self.assertEqual((r.status, r.code), (422, "validation_failed"), body)

    def test_item_errors_first_item_wins_and_in_item_order(self):
        bad_field = item(self.p1, -1)
        unknown = item("p_nope", 1)
        self.assertEqual(self.batch([unknown, bad_field]).code, "not_found")
        self.assertEqual(self.batch([bad_field, unknown]).code, "validation_failed")
        self.assertEqual(self.batch([item("p_nope", -1)]).code, "validation_failed")
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 10}, token=self.ada,
                 key=key()).body["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.bob,
                   key=key()).body["payment_id"]
        self.assertEqual(self.batch([item(cap, 1)]).code, "linked_payment_immutable")
        rf = call("POST", "/payments/%s/refunds" % self.p1, {"amount": 300}, token=self.bob,
                  key=key()).body["payment_id"]
        self.assertEqual(self.batch([item(rf, 1)]).code, "linked_payment_immutable")
        self.assertEqual(self.batch([item(cap, 1, expected=9)]).code,
                         "linked_payment_immutable")  # linked before stale
        self.assertEqual(self.batch([item(self.p1, 299, expected=9)]).code, "stale_revision")
        r = self.batch([item(self.p1, 299)])
        self.assertEqual((r.status, r.code), (422, "refund_exceeds_payment"))
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.assertEqual(self.batch([item(self.p1, 1, eff=future)]).code, "validation_failed")

    def test_settlement_checks(self):
        r = self.batch([item(self.members[0], 0)])
        self.assertEqual((r.status, r.code), (422, "incomplete_settlement"))
        r = self.batch([item(self.members[0], 0, eff=ago(1)), item(self.members[1], 0,
                                                                  eff=ago(2))])
        self.assertEqual((r.status, r.code), (422, "validation_failed"))
        r = self.batch([item(self.members[0], 0, expected=5), item(self.p1, 1)])
        self.assertEqual(r.code, "stale_revision")  # item errors before completeness

    def test_historical_overdraft_combined_and_nothing_changes(self):
        # bob starts at 0, receives 300, spends 300: moving the credit after the spend overdraws
        f = copy.deepcopy(FIXTURE)
        f["users"][1]["balance"] = 0
        f["users"][0]["balance"] = 12500
        f["payments"] = []  # keep the seeded history consistent with bob at 0
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        ada, bob = token("ada@example.com"), token("bob@example.com")
        credit = self.pay(ada, "bob", 300)
        spend = self.pay(bob, "cy", 300)
        before = (me(ada), me(bob), statement(bob).body["entries"])
        k = key()
        r = self.batch([item(credit, 300, eff=ago(0)), item(spend, 300, eff=ago(1))],
                       tok=token("cy@example.com"), k=k)
        self.assertEqual((r.status, r.code), (409, "historical_overdraft"))
        self.assertEqual((me(ada), me(bob), statement(bob).body["entries"]), before)
        ok = self.batch([item(credit, 300, eff=ago(2)), item(spend, 300, eff=ago(1))],
                        tok=token("cy@example.com"), k=k)
        self.assertEqual(ok.status, 201)  # same key reusable after the refusal


class ConcurrencyTest(Base):
    def test_batches_and_singles_sharing_a_revision_one_wins(self):
        results = []

        def single(i):
            results.append(call("POST", "/payments/%s/corrections" % self.p1,
                                {"expected_revision": 1, "amount": 900 - i,
                                 "effective_at": ago(0.5), "reason": "s"},
                                token=self.ada, key=key()))

        def batch(i):
            results.append(self.batch([item(self.p2, 400 + i), item(self.p1, 800 - i)]))
        threads = [threading.Thread(target=single if i % 2 else batch, args=(i,))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        winners = [r for r in results if r.status == 201]
        self.assertEqual(len(winners), 1, [r.status for r in results])
        self.assertTrue(all(r.code == "stale_revision" for r in results if r.status != 201))
        revs = call("GET", "/payments/%s/revisions" % self.p1, token=self.ada).body["revisions"]
        self.assertEqual(len(revs), 2)


if __name__ == "__main__":
    unittest.main()
