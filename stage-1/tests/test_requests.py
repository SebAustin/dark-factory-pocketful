import threading
import unittest
import uuid

from harness import call, reset
from test_payments import balances, token


def key():
    return uuid.uuid4().hex


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")
        self.bob = token("bob@example.com")
        self.cy = token("cy@example.com")

    def ask(self, tok, body, k=None):
        return call("POST", "/requests", body, token=tok, key=k or key())

    def pay(self, tok, rid, body=None, k=None, raw=None):
        return call("POST", "/requests/%s/pay" % rid, body if body is not None else {},
                    token=tok, key=k or key(), raw=raw)

    def act(self, tok, rid, verb):
        return call("POST", "/requests/%s/%s" % (rid, verb), token=tok)

    def new(self, payer="ada", amount=1200, note="taxi", tok=None):
        r = self.ask(tok or self.bob, {"payer_handle": payer, "amount": amount, "note": note})
        self.assertEqual(r.status, 201, r.raw)
        return r.body


class CreateTest(Base):
    def test_201_shape(self):
        b = self.new()
        self.assertEqual(
            {k: b[k] for k in ("requester_id", "requester_handle", "payer_id", "payer_handle",
                               "amount", "currency", "note", "status", "payment_id")},
            {"requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada",
             "payer_handle": "ada", "amount": 1200, "currency": "EUR", "note": "taxi",
             "status": "pending", "payment_id": None})
        self.assertNotEqual(b["request_id"], "rq_1")
        self.assertRegex(b["created_at"], r"\+00:00$")

    def test_may_exceed_payer_balance(self):
        b = self.new(payer="cy", amount=1000000000)
        self.assertEqual(b["status"], "pending")
        self.assertEqual(balances()["cy"], 0)

    def test_errors(self):
        r = self.ask(self.bob, {"payer_handle": "bob", "amount": 1})
        self.assertEqual((r.status, r.code), (422, "self_request"))
        r = self.ask(self.bob, {"payer_handle": "nobody", "amount": 1})
        self.assertEqual((r.status, r.code), (404, "not_found"))
        for amount in (0, 1000000001, 2.5, "5", True, None):
            r = self.ask(self.bob, {"payer_handle": "ada", "amount": amount})
            self.assertEqual((r.status, r.code), (422, "validation_failed"), amount)
        r = self.ask(self.bob, {"payer_handle": "ada", "amount": 1, "note": "x" * 201})
        self.assertEqual(r.status, 422)
        r = self.ask(self.bob, {"payer_handle": "ada", "amount": 1, "note": None})
        self.assertEqual(r.status, 422)
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 1}, token=self.bob)
        self.assertEqual(r.code, "missing_idempotency_key")

    def test_replay(self):
        k = key()
        a = self.ask(self.bob, {"payer_handle": "ada", "amount": 5}, k)
        b = self.ask(self.bob, {"amount": 5.0, "payer_handle": "ada"}, k)
        self.assertEqual((a.status, b.status), (201, 200))
        self.assertEqual(a.body, b.body)
        c = self.ask(self.bob, {"payer_handle": "ada", "amount": 6}, k)
        self.assertEqual(c.code, "idempotency_key_reuse")

    def test_requests_not_in_activity(self):
        self.new()
        feed = call("GET", "/activity", token=self.ada).body["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_1"])


class PayTest(Base):
    def test_pay_creates_payment_and_marks_paid(self):
        rq = self.new()
        r = self.pay(self.ada, rq["request_id"], {"visibility": "private"})
        self.assertEqual(r.status, 201, r.raw)
        p = r.body
        self.assertEqual((p["from_user_id"], p["to_user_id"], p["amount"], p["note"],
                          p["visibility"], p["request_id"]),
                         ("u_ada", "u_bob", 1200, "taxi", "private", rq["request_id"]))
        self.assertEqual(balances(), {"ada": 8800, "bob": 3700, "cy": 0})
        listed = call("GET", "/requests", token=self.bob).body["requests"][0]
        self.assertEqual((listed["status"], listed["payment_id"]), ("paid", p["payment_id"]))
        feed_cy = call("GET", "/activity", token=self.cy).body["payments"]
        self.assertNotIn(p["payment_id"], [x["payment_id"] for x in feed_cy])
        feed_bob = call("GET", "/activity", token=self.bob).body["payments"]
        self.assertEqual(feed_bob[0], p)

    def test_default_visibility_public(self):
        rq = self.new()
        self.assertEqual(self.pay(self.ada, rq["request_id"]).body["visibility"], "public")

    def test_seeded_request_payable(self):
        self.assertEqual(self.pay(self.ada, "rq_1").status, 201)

    def test_insufficient_then_payable_later(self):
        rq = self.new(payer="cy", amount=500)
        r = self.pay(self.cy, rq["request_id"])
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))
        listed = call("GET", "/requests", token=self.cy).body["requests"][0]
        self.assertEqual(listed["status"], "pending")
        call("POST", "/payments", {"to_handle": "cy", "amount": 500}, token=self.ada, key=key())
        self.assertEqual(self.pay(self.cy, rq["request_id"]).status, 201)
        self.assertEqual(balances()["cy"], 0)

    def test_permissions_and_unknown(self):
        rq = self.new()
        r = self.pay(self.bob, rq["request_id"])
        self.assertEqual((r.status, r.code), (403, "forbidden"))
        r = self.pay(self.cy, rq["request_id"])
        self.assertEqual((r.status, r.code), (403, "forbidden"))
        r = self.pay(self.ada, "rq_nope")
        self.assertEqual((r.status, r.code), (404, "not_found"))

    def test_not_pending(self):
        rq = self.new()
        self.act(self.ada, rq["request_id"], "decline")
        r = self.pay(self.ada, rq["request_id"])
        self.assertEqual((r.status, r.code), (409, "request_not_pending"))

    def test_bad_visibility(self):
        rq = self.new()
        r = self.pay(self.ada, rq["request_id"], {"visibility": "secret"})
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_replay_after_paid_is_200_not_409(self):
        rq = self.new()
        k = key()
        first = self.pay(self.ada, rq["request_id"], {}, k)
        again = self.pay(self.ada, rq["request_id"], {}, k)
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(first.body, again.body)
        self.assertEqual(balances()["ada"], 8800)
        other = self.pay(self.ada, rq["request_id"], {}, key())
        self.assertEqual(other.code, "request_not_pending")

    def test_empty_vs_explicit_public_is_reuse(self):
        rq = self.new()
        k = key()
        self.assertEqual(self.pay(self.ada, rq["request_id"], {}, k).status, 201)
        r = self.pay(self.ada, rq["request_id"], {"visibility": "public"}, k)
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))

    def test_same_key_other_request_is_new(self):
        a, b = self.new(amount=1), self.new(amount=2)
        k = key()
        self.assertEqual(self.pay(self.ada, a["request_id"], {}, k).status, 201)
        self.assertEqual(self.pay(self.ada, b["request_id"], {}, k).status, 201)

    def test_concurrent_pays_distinct_keys_move_money_once(self):
        rq = self.new(amount=100)
        results = []

        def go():
            results.append(self.pay(self.ada, rq["request_id"]))
        threads = [threading.Thread(target=go) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = [r.status for r in results]
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertTrue(all(r.code == "request_not_pending" for r in results if r.status != 201))
        self.assertEqual(balances()["ada"], 9900)


class DeclineCancelTest(Base):
    def test_decline_idempotent_and_conflicts(self):
        rq = self.new()
        rid = rq["request_id"]
        self.assertEqual(self.act(self.bob, rid, "decline").code, "forbidden")
        self.assertEqual(self.act(self.cy, rid, "decline").status, 403)
        r = self.act(self.ada, rid, "decline")
        self.assertEqual((r.status, r.body["status"]), (200, "declined"))
        self.assertEqual(r.body["request_id"], rid)
        r2 = self.act(self.ada, rid, "decline")
        self.assertEqual((r2.status, r2.body), (200, r.body))
        self.assertEqual(self.act(self.bob, rid, "cancel").code, "request_not_pending")

    def test_cancel_idempotent_and_conflicts(self):
        rq = self.new()
        rid = rq["request_id"]
        self.assertEqual(self.act(self.ada, rid, "cancel").code, "forbidden")
        r = self.act(self.bob, rid, "cancel")
        self.assertEqual((r.status, r.body["status"]), (200, "cancelled"))
        self.assertEqual(self.act(self.bob, rid, "cancel").status, 200)
        self.assertEqual(self.act(self.ada, rid, "decline").code, "request_not_pending")
        self.assertEqual(self.pay(self.ada, rid).code, "request_not_pending")

    def test_paid_cannot_be_declined_or_cancelled(self):
        rq = self.new()
        self.pay(self.ada, rq["request_id"])
        self.assertEqual(self.act(self.ada, rq["request_id"], "decline").status, 409)
        self.assertEqual(self.act(self.bob, rq["request_id"], "cancel").status, 409)

    def test_unknown_404_and_body_handling(self):
        self.assertEqual(self.act(self.ada, "rq_x", "decline").code, "not_found")
        self.assertEqual(self.act(self.ada, "rq_x", "cancel").code, "not_found")
        r = call("POST", "/requests/rq_1/decline", raw="{bad", token=self.ada)
        self.assertEqual(r.code, "malformed_request")
        r = call("POST", "/requests/rq_1/decline", {"anything": 1}, token=self.ada)
        self.assertEqual(r.status, 200)

    def test_auth_required(self):
        self.assertEqual(call("POST", "/requests/rq_1/decline").status, 401)


class ListTest(Base):
    def ids(self, tok, query=""):
        r = call("GET", "/requests" + query, token=tok)
        self.assertEqual(r.status, 200, r.raw)
        return [x["request_id"] for x in r.body["requests"]], r.body["has_more"]

    def test_party_scoping_and_order(self):
        a = self.new()["request_id"]                       # bob asks ada
        b = self.new(payer="bob", tok=self.ada)["request_id"]  # ada asks bob
        c = self.new(payer="cy")["request_id"]             # bob asks cy
        self.assertEqual(self.ids(self.ada), ([b, a, "rq_1"], False))
        self.assertEqual(self.ids(self.cy), ([c], False))
        self.assertEqual(self.ids(self.ada, "?direction=incoming")[0], [a, "rq_1"])
        self.assertEqual(self.ids(self.ada, "?direction=outgoing")[0], [b])
        self.act(self.ada, a, "decline")
        self.assertEqual(self.ids(self.ada, "?status=declined")[0], [a])
        self.assertEqual(self.ids(self.ada, "?status=pending&direction=incoming")[0], ["rq_1"])
        self.assertEqual(self.ids(self.ada, "?status=paid")[0], [])

    def test_pagination(self):
        made = [self.new(amount=i + 1)["request_id"] for i in range(4)]
        ids, more = self.ids(self.ada, "?limit=2")
        self.assertEqual((ids, more), ([made[3], made[2]], True))
        ids, more = self.ids(self.ada, "?limit=2&offset=4")
        self.assertEqual((ids, more), (["rq_1"], False))

    def test_bad_query(self):
        for q in ("direction=sideways", "direction=", "status=open", "status=", "limit=0",
                  "limit=201", "limit=1e2", "offset=-1", "offset=+1"):
            r = call("GET", "/requests?" + q, token=self.ada)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), q)


if __name__ == "__main__":
    unittest.main()
