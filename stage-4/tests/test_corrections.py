"""S3.4: payment corrections and revisions (stage 3; D-46, D-47, D-53, D-56..D-59)."""
import copy
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from harness import FIXTURE, call, reset
from test_payments import token
from test_statement import statement

REV_KEYS = ["payment_id", "revision", "amount", "effective_at", "recorded_at", "reason",
            "correction_batch_id"]


def iso(dt):
    return dt.isoformat(timespec="microseconds")


def ago(hours):
    return iso(datetime.now(timezone.utc) - timedelta(hours=hours))


def key():
    return uuid.uuid4().hex


def me(tok, **params):
    from urllib.parse import quote
    q = "&".join("{}={}".format(k, quote(v, safe="")) for k, v in params.items())
    return call("GET", "/me" + ("?" + q if q else ""), token=tok).body


class Base(unittest.TestCase):
    def setUp(self):
        self.t1, self.t2 = ago(5), ago(4)
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                          "amount": 500, "note": "coffee", "created_at": self.t1}]
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))

    def correct(self, pid, body, tok=None, k=None):
        return call("POST", "/payments/%s/corrections" % pid, body, token=tok or self.ada,
                    key=k or key())

    def body(self, **over):
        b = {"expected_revision": 1, "amount": 400, "effective_at": self.t1,
             "reason": "corrected amount"}
        b.update(over)
        return b

    def revisions(self, pid, tok=None):
        return call("GET", "/payments/%s/revisions" % pid, token=tok or self.ada)


class CorrectionTest(Base):
    def test_201_shape_and_money_moves_between_the_same_wallets(self):
        r = self.correct("p_1", self.body(amount=400))
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(list(r.body), REV_KEYS)
        self.assertEqual((r.body["payment_id"], r.body["revision"], r.body["amount"],
                          r.body["effective_at"], r.body["reason"]),
                         ("p_1", 2, 400, self.t1, "corrected amount"))
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (10100, 2400))
        r = self.correct("p_1", self.body(expected_revision=2, amount=700))  # increase
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (9800, 2700))
        self.assertEqual(me(self.ada)["balance"] + me(self.bob)["balance"]
                         + me(self.cy)["balance"], 12500)

    def test_history_and_statement_follow_selected_revisions(self):
        r = self.correct("p_1", self.body(amount=0, effective_at=self.t2))  # zero reverses
        rec = r.body["recorded_at"]
        self.assertEqual(me(self.ada)["balance"], 10500)
        self.assertEqual(me(self.ada, as_of=self.t1)["balance"], 10500)  # moved to t2
        self.assertEqual(me(self.ada, as_of=self.t1, known_at=self.t2)["balance"], 10000)
        s = statement(self.ada).body
        e = s["entries"][0]
        self.assertEqual((e["payment"]["amount"], e["delta"], e["revision"], e["effective_at"],
                          e["recorded_at"]), (0, 0, 2, self.t2, rec))
        self.assertEqual(len(s["entries"]), 1)  # one entry per payment
        old = statement(self.ada, known_at=self.t2).body["entries"][0]
        self.assertEqual((old["revision"], old["delta"]), (1, -500))
        moved = statement(self.ada, **{"from": self.t1, "to": self.t2}).body
        self.assertEqual(moved["entries"], [])  # moved out of [t1, t2)

    def test_existing_surfaces_unchanged(self):  # D-56
        feed_before = call("GET", "/activity", token=self.ada).body
        self.correct("p_1", self.body(amount=1))
        self.assertEqual(call("GET", "/activity", token=self.ada).body, feed_before)

    def test_same_amount_and_replay(self):
        k = key()
        first = self.correct("p_1", self.body(amount=500, effective_at=self.t2), k=k)
        self.assertEqual(first.status, 201)
        self.correct("p_1", self.body(expected_revision=2, amount=300))
        again = self.correct("p_1", self.body(amount=500, effective_at=self.t2), k=k)
        self.assertEqual((again.status, again.body), (200, first.body))  # original revision
        reuse = self.correct("p_1", self.body(amount=499, effective_at=self.t2), k=k)
        self.assertEqual(reuse.code, "idempotency_key_reuse")
        self.assertEqual(me(self.ada)["balance"], 10200)

    def test_recorded_at_strictly_increases(self):
        recs = []
        for i in range(3):
            recs.append(self.correct("p_1", self.body(expected_revision=i + 1,
                                                      amount=400 - i)).body["recorded_at"])
        r = self.revisions("p_1")
        self.assertEqual([x["revision"] for x in r.body["revisions"]], [1, 2, 3, 4])
        self.assertEqual([x["recorded_at"] for x in r.body["revisions"]][1:], recs)
        self.assertEqual(recs, sorted(set(recs)))


class ErrorTest(Base):
    def test_field_errors_are_422(self):
        for over in ({"expected_revision": 0}, {"expected_revision": "1"},
                     {"expected_revision": True}, {"expected_revision": 1.5},
                     {"amount": -1}, {"amount": 1000000001}, {"amount": "4"}, {"amount": None},
                     {"effective_at": "2026-09-24"}, {"effective_at": 5},
                     {"effective_at": iso(datetime.now(timezone.utc) + timedelta(hours=1))},
                     {"reason": ""}, {"reason": "x" * 201}, {"reason": 7}):
            r = self.correct("p_1", self.body(**over))
            self.assertEqual((r.status, r.code), (422, "validation_failed"), over)
        for missing in ("expected_revision", "amount", "effective_at", "reason"):
            b = self.body()
            b.pop(missing)
            self.assertEqual(self.correct("p_1", b).code, "validation_failed", missing)
        self.assertEqual(self.correct("p_1", self.body(expected_revision=1.0)).status, 201)

    def test_order_404_403_linked_stale(self):
        self.assertEqual(self.correct("p_nope", self.body()).code, "not_found")
        self.assertEqual(self.correct("p_1", self.body(), tok=self.bob).code, "forbidden")
        self.assertEqual(self.correct("p_1", self.body(), tok=self.cy).code, "forbidden")
        self.assertEqual(self.correct("p_1", self.body(reason="")).code, "validation_failed")
        self.assertEqual(self.correct("p_nope", self.body(reason="")).code,
                         "validation_failed")  # fields before 404
        r = self.correct("p_1", self.body(expected_revision=2))
        self.assertEqual((r.status, r.code), (409, "stale_revision"))
        r = call("POST", "/payments/p_1/corrections", raw="[1]", token=self.ada, key=key())
        self.assertEqual(r.code, "malformed_request")
        r = call("POST", "/payments/p_1/corrections", self.body(), token=self.ada)
        self.assertEqual(r.code, "missing_idempotency_key")
        self.assertEqual(call("POST", "/payments/p_1/corrections", self.body(),
                              key=key()).status, 401)

    def test_linked_payments_are_immutable(self):
        st = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 10}]}, token=self.cy, key=key())
        member = st.body["payments"][0]["payment_id"]
        r = self.correct(member, self.body())
        self.assertEqual((r.status, r.code), (422, "linked_payment_immutable"))
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 50}, token=self.ada,
                 key=key()).body["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.bob,
                   key=key()).body["payment_id"]
        self.assertEqual(self.correct(cap, self.body()).code, "linked_payment_immutable")
        self.assertEqual(self.correct(cap, self.body(), tok=self.bob).code, "forbidden")

    def test_insufficient_funds_before_historical(self):
        # decrease debits the receiver: bob would need 2000 more than he has
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_cy",
                          "amount": 5000, "created_at": self.t1}]
        f["users"][0]["balance"], f["users"][2]["balance"] = 5000, 5000
        reset(f)
        ada = token("ada@example.com")
        call("POST", "/payments", {"to_handle": "bob", "amount": 4000},
             token=token("cy@example.com"), key=key())
        r = self.correct("p_1", self.body(amount=0), tok=ada)
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))

    def test_overdraft_via_moved_credit(self):
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300,
             "created_at": self.t1},
            {"id": "p_2", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 300,
             "created_at": self.t2}]
        f["users"][0]["balance"] = 9700
        f["users"][1]["balance"] = 2800
        f["users"][2]["balance"] = 0
        reset(f)
        ada, cy = token("ada@example.com"), token("cy@example.com")
        before = (me(ada), me(cy), self.revisions("p_1", ada).body,
                  statement(cy).body["entries"])
        k = key()
        r = self.correct("p_1", self.body(amount=300, effective_at=ago(3)), tok=ada, k=k)
        self.assertEqual((r.status, r.code), (409, "historical_overdraft"))  # cy at t2 < 0
        after = (me(ada), me(cy), self.revisions("p_1", ada).body,
                 statement(cy).body["entries"])
        self.assertEqual(after, before)
        ok = self.correct("p_1", self.body(amount=300, effective_at=self.t2), tok=ada, k=k)
        self.assertEqual(ok.status, 201)  # same instant as cy's spend: combined, and key reusable

    def test_overdraft_on_available_via_hold(self):
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_cy",
                          "amount": 300, "created_at": self.t1}]
        f["users"][0]["balance"], f["users"][2]["balance"] = 9700, 300
        reset(f)
        ada, cy = token("ada@example.com"), token("cy@example.com")
        call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, token=cy,
             key=key())  # cy holds all 300 from now on
        r = self.correct("p_1", self.body(amount=300, effective_at=iso(
            datetime.now(timezone.utc))), tok=ada)
        self.assertIn(r.code, ("insufficient_funds", "historical_overdraft"))


class RevisionsEndpointTest(Base):
    def test_shape_and_access(self):
        r = self.revisions("p_1")
        self.assertEqual(r.body, {"revisions": [{"payment_id": "p_1", "revision": 1,
                                                 "amount": 500, "effective_at": self.t1,
                                                 "recorded_at": self.t1, "reason": "",
                                                 "correction_batch_id": None}]})
        self.assertEqual(self.revisions("p_1", tok=self.bob).status, 200)
        self.assertEqual(self.revisions("p_1", tok=self.cy).code, "not_found")  # public too
        self.assertEqual(self.revisions("p_nope").code, "not_found")
        self.assertEqual(call("GET", "/payments/p_1/revisions").status, 401)


class ConcurrencyTest(Base):
    def test_same_expected_revision_one_wins(self):
        results = []

        def go(i):
            results.append(self.correct("p_1", self.body(amount=400 - i)))
        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = sorted(r.status for r in results)
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertTrue(all(r.code == "stale_revision" for r in results if r.status != 201))
        self.assertEqual(len(self.revisions("p_1").body["revisions"]), 2)


if __name__ == "__main__":
    unittest.main()
