"""S4.1: refunds (stage 4) and the correction rules they add."""
import copy
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from harness import FIXTURE, call, reset
from test_payments import token
from test_statement import statement


def key():
    return uuid.uuid4().hex


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="microseconds")


def me(tok):
    return call("GET", "/me", token=tok).body


class Base(unittest.TestCase):
    def setUp(self):
        f = copy.deepcopy(FIXTURE)
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))
        self.pay = call("POST", "/payments", {"to_handle": "bob", "amount": 1000,
                                              "note": "dinner", "visibility": "private"},
                        token=self.ada, key=key()).body

    def refund(self, pid, amount, tok=None, k=None, raw=None):
        return call("POST", "/payments/%s/refunds" % pid,
                    None if raw is not None else {"amount": amount},
                    token=tok or self.bob, key=k or key(), raw=raw)

    def correct(self, pid, amount, expected=1, tok=None):
        return call("POST", "/payments/%s/corrections" % pid,
                    {"expected_revision": expected, "amount": amount, "effective_at": ago(0.01),
                     "reason": "fix"}, token=tok or self.ada, key=key())


class RefundTest(Base):
    def test_201_is_an_opposite_payment(self):
        r = self.refund(self.pay["payment_id"], 300)
        self.assertEqual(r.status, 201, r.raw)
        b = r.body
        self.assertEqual((b["from_user_id"], b["to_user_id"], b["amount"], b["note"],
                          b["visibility"], b["refund_of"], b["request_id"],
                          b["authorization_id"], b["settlement_id"]),
                         ("u_bob", "u_ada", 300, "dinner", "private", self.pay["payment_id"],
                          None, None, None))
        self.assertEqual(len(b), 14)
        self.assertIsNone(self.pay["refund_of"])
        self.assertEqual((me(self.ada)["balance"], me(self.bob)["balance"]), (9300, 3200))
        feed = call("GET", "/activity", token=self.bob).body["payments"]
        self.assertEqual(feed[0], b)
        entries = statement(self.ada).body["entries"]
        self.assertEqual(entries[-1]["payment"]["payment_id"], b["payment_id"])
        self.assertEqual(entries[-1]["delta"], 300)

    def test_cumulative_cap_and_replay(self):
        pid = self.pay["payment_id"]
        k = key()
        first = self.refund(pid, 600, k=k)
        again = self.refund(pid, 600, k=k)
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(again.body, first.body)
        self.assertEqual(self.refund(pid, 401).code, "refund_exceeds_payment")
        self.assertEqual(self.refund(pid, 400).status, 201)
        self.assertEqual(self.refund(pid, 1).code, "refund_exceeds_payment")
        self.assertEqual(self.refund(pid, 1, k=k).code, "idempotency_key_reuse")

    def test_cap_follows_the_corrected_amount(self):
        pid = self.pay["payment_id"]
        self.assertEqual(self.correct(pid, 500).status, 201)
        self.assertEqual(self.refund(pid, 501).code, "refund_exceeds_payment")
        self.assertEqual(self.refund(pid, 300).status, 201)
        r = self.correct(pid, 299, expected=2)
        self.assertEqual((r.status, r.code), (422, "refund_exceeds_payment"))
        self.assertEqual(self.correct(pid, 300, expected=2).status, 201)

    def test_errors_and_order(self):
        pid = self.pay["payment_id"]
        for amount in (0, -1, 1000000001, 1.5, "5", True, None):
            r = self.refund(pid, amount)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), amount)
        self.assertEqual(self.refund(pid, None, raw="{}").code, "validation_failed")
        self.assertEqual(self.refund("p_nope", 1).code, "not_found")
        self.assertEqual(self.refund(pid, 1, tok=self.ada).code, "forbidden")  # the sender
        self.assertEqual(self.refund(pid, 1, tok=self.cy).code, "forbidden")
        self.assertEqual(self.refund("p_nope", 0).code, "validation_failed")  # fields first
        r = call("POST", "/payments/%s/refunds" % pid, {"amount": 1}, token=self.bob)
        self.assertEqual(r.code, "missing_idempotency_key")
        self.assertEqual(call("POST", "/payments/%s/refunds" % pid, {"amount": 1},
                              key=key()).status, 401)

    def test_refund_of_refund_and_corrections_of_refunds(self):
        rf = self.refund(self.pay["payment_id"], 100).body["payment_id"]
        r = self.refund(rf, 1, tok=self.ada)  # ada is the refund's receiver
        self.assertEqual((r.status, r.code), (422, "invalid_refund_target"))
        self.assertEqual(self.refund(rf, 1, tok=self.bob).code, "forbidden")
        r = self.correct(rf, 50, tok=self.bob)
        self.assertEqual((r.status, r.code), (422, "linked_payment_immutable"))

    def test_insufficient_available_including_holds(self):
        pid = self.pay["payment_id"]
        call("POST", "/authorizations", {"to_handle": "cy", "amount": 3000}, token=self.bob,
             key=key())  # bob: total 3500, held 3000, available 500
        r = self.refund(pid, 501)
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))
        self.assertEqual(self.refund(pid, 500).status, 201)

    def test_targets_request_capture_settlement(self):
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 70}, token=self.bob,
                  key=key()).body["request_id"]
        paid = call("POST", "/requests/%s/pay" % rq, {}, token=self.ada, key=key()).body
        self.assertEqual(self.refund(paid["payment_id"], 70).status, 201)
        listed = call("GET", "/requests", token=self.bob).body["requests"][0]
        self.assertEqual(listed["status"], "paid")  # never reopened
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 90}, token=self.ada,
                 key=key()).body["authorization_id"]
        cap = call("POST", "/authorizations/%s/capture" % a, {}, token=self.bob,
                   key=key()).body
        self.assertEqual(self.refund(cap["payment_id"], 90).status, 201)
        auth = [x for x in call("GET", "/authorizations", token=self.ada).body[
            "authorizations"] if x["authorization_id"] == a][0]
        self.assertEqual((auth["status"], auth["captured_amount"]), ("captured", 90))
        self.assertEqual(me(self.ada)["held"], 0)
        st = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 25}]}, token=self.cy,
            key=key()).body
        member = st["payments"][0]["payment_id"]
        r = self.refund(member, 25)
        self.assertEqual(r.status, 201)
        self.assertEqual(r.body["settlement_id"], None)

    def test_totals_conserved_and_history_includes_refunds(self):
        pid = self.pay["payment_id"]
        made = self.refund(pid, 250).body
        ks = [token(e + "@example.com") for e in ("ada", "bob", "cy")]
        self.assertEqual(sum(me(t)["total"] for t in ks), 12500)
        from urllib.parse import quote
        before = call("GET", "/me?as_of=" + quote(self.pay["created_at"], safe=""),
                      token=self.ada).body
        self.assertEqual(before["balance"], 9000)
        after = call("GET", "/me?as_of=" + quote(made["created_at"], safe=""),
                     token=self.ada).body
        self.assertEqual(after["balance"], 9250)


class RefundRaceTest(Base):
    def test_concurrent_refunds_never_exceed(self):
        pid = self.pay["payment_id"]
        results = []

        def go():
            results.append(self.refund(pid, 300))
        threads = [threading.Thread(target=go) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r.status == 201 for r in results), 3)
        self.assertTrue(all(r.code == "refund_exceeds_payment"
                            for r in results if r.status != 201))
        self.assertEqual(me(self.bob)["balance"], 2600)


if __name__ == "__main__":
    unittest.main()
