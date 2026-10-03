"""S2.3 POST/GET /authorizations; S2.4 capture and void (stage 2 API)."""
import threading
import time
import unittest
import uuid
from datetime import datetime

from harness import call, reset
from test_holds import ClockCase, fixture, hold, me
from test_payments import token

from app.store import STORE

VIEW_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
             "amount", "captured_amount", "remaining_amount", "currency", "note", "visibility",
             "status", "expires_at", "payment_id", "payment_ids", "created_at"}


def key():
    return uuid.uuid4().hex


class Base(ClockCase):
    def setUp(self):
        super().setUp()
        reset(fixture(authorization_ttl_seconds=600))
        self.ada = token("ada@example.com")
        self.bob = token("bob@example.com")
        self.cy = token("cy@example.com")

    def authorize(self, body, tok=None, k=None):
        return call("POST", "/authorizations", body, token=tok or self.ada, key=k or key())

    def new(self, amount=2000, to="bob", **extra):
        r = self.authorize({"to_handle": to, "amount": amount, **extra})
        self.assertEqual(r.status, 201, r.raw)
        return r.body

    def listing(self, tok, query=""):
        r = call("GET", "/authorizations" + query, token=tok)
        self.assertEqual(r.status, 200, r.raw)
        return r.body


class CreateTest(Base):
    def test_201_shape_and_hold(self):
        b = self.new(2000, note="deposit", visibility="private")
        self.assertEqual(set(b), VIEW_KEYS)
        self.assertEqual({k: b[k] for k in ("from_user_id", "from_handle", "to_user_id",
                                            "to_handle", "amount", "captured_amount",
                                            "remaining_amount", "currency", "note",
                                            "visibility", "status", "payment_id",
                                            "payment_ids")},
                         {"from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob",
                          "to_handle": "bob", "amount": 2000, "captured_amount": 0,
                          "remaining_amount": 2000, "currency": "EUR", "note": "deposit",
                          "visibility": "private", "status": "open", "payment_id": None,
                          "payment_ids": []})
        created = datetime.fromisoformat(b["created_at"])
        expires = datetime.fromisoformat(b["expires_at"])
        self.assertEqual((expires - created).total_seconds(), 600)
        self.assertRegex(b["expires_at"], r"[+-]\d\d:\d\d$")
        body = me(self.ada)
        self.assertEqual((body["total"], body["available"], body["held"]), (10000, 8000, 2000))

    def test_defaults(self):
        b = self.new(1)
        self.assertEqual((b["note"], b["visibility"]), ("", "public"))

    def test_insufficient_available(self):
        self.new(8000)
        r = self.authorize({"to_handle": "bob", "amount": 2001})
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))
        self.assertEqual(self.authorize({"to_handle": "bob", "amount": 2000}).status, 201)
        self.assertEqual(me(self.ada)["available"], 0)
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada,
                 key=key())
        self.assertEqual(r.code, "insufficient_funds")

    def test_error_table(self):
        cases = [({"to_handle": "bob", "amount": 0}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": 1.5}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": "5"}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": True}, 422, "validation_failed"),
                 ({"to_handle": "ada", "amount": 1}, 422, "self_payment"),
                 ({"to_handle": "bob", "amount": 1, "note": "x" * 201}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": 1, "note": None}, 422, "validation_failed"),
                 ({"to_handle": "bob", "amount": 1, "visibility": "secret"}, 422,
                  "validation_failed"),
                 ({"to_handle": "nobody", "amount": 1}, 404, "not_found"),
                 ({"to_handle": 5, "amount": 1}, 400, "malformed_request"),
                 ({"amount": 1}, 422, "validation_failed")]
        for body, status, code in cases:
            r = self.authorize(body)
            self.assertEqual((r.status, r.code), (status, code), body)
        self.assertEqual(me(self.ada)["held"], 0)
        r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, token=self.ada)
        self.assertEqual(r.code, "missing_idempotency_key")
        r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1}, key=key())
        self.assertEqual(r.status, 401)

    def test_idempotent_replay(self):
        k = key()
        first = self.authorize({"to_handle": "bob", "amount": 100}, k=k)
        again = self.authorize({"amount": 1e2, "to_handle": "bob"}, k=k)
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(first.body, again.body)
        self.assertEqual(me(self.ada)["held"], 100)
        self.assertEqual(self.authorize({"to_handle": "bob", "amount": 101}, k=k).code,
                         "idempotency_key_reuse")

    def test_concurrent_holds_never_exceed_available(self):
        results = []

        def go():
            results.append(self.authorize({"to_handle": "bob", "amount": 1000}))
        threads = [threading.Thread(target=go) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r.status == 201 for r in results), 10)
        self.assertTrue(all(r.status in (201, 409) for r in results))
        body = me(self.ada)
        self.assertEqual((body["held"], body["available"], body["total"]), (10000, 0, 10000))

    def test_not_a_feed_item_and_no_money_moves(self):
        self.new(2000)
        feed = call("GET", "/activity", token=self.bob).body["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_1"])
        self.assertEqual(me(self.bob)["total"], 2500)


class ListTest(Base):
    def test_party_scoping_direction_status_order(self):
        a1 = self.new(100)["authorization_id"]                          # ada -> bob
        a2 = self.authorize({"to_handle": "ada", "amount": 50}, tok=self.bob).body[
            "authorization_id"]                                         # bob -> ada
        a3 = self.new(10, to="cy")["authorization_id"]                  # ada -> cy
        ids = lambda tok, q="": [a["authorization_id"]
                                 for a in self.listing(tok, q)["authorizations"]]
        self.assertEqual(ids(self.ada), [a3, a2, a1])
        self.assertEqual(ids(self.bob), [a2, a1])
        self.assertEqual(ids(self.cy), [a3])
        self.assertEqual(ids(self.ada, "?direction=outgoing"), [a3, a1])
        self.assertEqual(ids(self.ada, "?direction=incoming"), [a2])
        self.assertEqual(ids(self.ada, "?status=open"), [a3, a2, a1])
        self.assertEqual(ids(self.ada, "?status=voided"), [])
        page = self.listing(self.ada, "?limit=2")
        self.assertEqual(([a["authorization_id"] for a in page["authorizations"]],
                          page["has_more"]), ([a3, a2], True))
        self.assertFalse(self.listing(self.ada, "?limit=2&offset=1")["has_more"])
        self.assertEqual(set(page["authorizations"][0]), VIEW_KEYS)

    def test_bad_query(self):
        for q in ("direction=sideways", "status=pending", "status=", "limit=0", "limit=201",
                  "offset=-1", "limit=1e2"):
            r = call("GET", "/authorizations?" + q, token=self.ada)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), q)
        self.assertEqual(call("GET", "/authorizations").status, 401)

    def test_clock_expiry_is_listed_as_expired_never_open(self):
        aid = self.new(2000)["authorization_id"]
        self.advance(600)
        self.assertEqual(self.listing(self.ada, "?status=open")["authorizations"], [])
        expired = self.listing(self.ada, "?status=expired")["authorizations"]
        self.assertEqual([a["authorization_id"] for a in expired], [aid])
        self.assertEqual((expired[0]["status"], expired[0]["remaining_amount"]), ("expired", 0))
        self.assertEqual(me(self.ada)["available"], 10000)

    def test_seeded_authorizations_listed(self):
        reset(fixture(hold("a_1", amount=300), hold("a_2", to="u_cy", status="voided")))
        ada = token("ada@example.com")
        listed = self.listing(ada)["authorizations"]
        self.assertEqual({a["authorization_id"]: a["status"] for a in listed},
                         {"a_1": "open", "a_2": "voided"})


if __name__ == "__main__":
    unittest.main()
