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
             "status", "expires_at", "payment_id", "payment_ids", "created_at", "closed_at"}


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


class CaptureTest(Base):
    def capture(self, aid, body=None, tok=None, k=None):
        return call("POST", "/authorizations/%s/capture" % aid, {} if body is None else body,
                    token=tok or self.bob, key=k or key())

    def view(self, aid, tok=None):
        for a in self.listing(tok or self.ada)["authorizations"]:
            if a["authorization_id"] == aid:
                return a
        raise AssertionError("not listed")

    def test_default_full_capture(self):
        aid = self.new(2000, note="deposit", visibility="private")["authorization_id"]
        r = self.capture(aid)
        self.assertEqual(r.status, 201, r.raw)
        p = r.body
        self.assertEqual(len(p), 13)
        self.assertEqual((p["from_user_id"], p["to_user_id"], p["amount"], p["note"],
                          p["visibility"], p["authorization_id"], p["request_id"]),
                         ("u_ada", "u_bob", 2000, "deposit", "private", aid, None))
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"],
                          a["payment_id"], a["payment_ids"]),
                         ("captured", 2000, 0, p["payment_id"], [p["payment_id"]]))
        ada, bob = me(self.ada), me(self.bob)
        self.assertEqual((ada["total"], ada["held"], ada["available"]), (8000, 0, 8000))
        self.assertEqual(bob["total"], 4500)
        feed = call("GET", "/activity", token=self.bob).body["payments"]
        self.assertEqual(feed[0], p)
        cy_feed = call("GET", "/activity", token=self.cy).body["payments"]
        self.assertNotIn(p["payment_id"], [x["payment_id"] for x in cy_feed])

    def test_partial_final_capture_releases_remainder_in_same_step(self):
        aid = self.new(2000)["authorization_id"]
        r = self.capture(aid, {"amount": 1500})
        self.assertEqual(r.body["amount"], 1500)
        ada = me(self.ada)
        self.assertEqual((ada["total"], ada["held"], ada["available"]), (8500, 0, 8500))
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"]),
                         ("captured", 1500, 0))
        r = self.capture(aid, {"amount": 1})
        self.assertEqual((r.status, r.code), (409, "authorization_not_open"))

    def test_extended_capture_chain(self):
        aid = self.new(2000)["authorization_id"]
        p1 = self.capture(aid, {"amount": 700, "final": False}).body
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"]),
                         ("open", 700, 1300))
        self.assertEqual(me(self.ada)["held"], 1300)
        r = self.capture(aid, {"amount": 1301, "final": False})
        self.assertEqual((r.status, r.code), (422, "capture_exceeds_authorization"))
        p2 = self.capture(aid, {"amount": 300, "final": False}).body
        p3 = self.capture(aid, {"final": False}).body  # omitted amount = the remainder (1000)
        self.assertEqual(p3["amount"], 1000)
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"],
                          a["payment_ids"], a["payment_id"]),
                         ("captured", 2000, 0,
                          [p1["payment_id"], p2["payment_id"], p3["payment_id"]],
                          p3["payment_id"]))
        ada = me(self.ada)
        self.assertEqual((ada["total"], ada["held"]), (8000, 0))

    def test_nonfinal_then_final_releases_rest(self):
        aid = self.new(2000)["authorization_id"]
        self.capture(aid, {"amount": 500, "final": False})
        self.capture(aid, {"amount": 200, "final": True})
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"]), ("captured", 700))
        self.assertEqual(me(self.ada)["available"], 9300)

    def test_error_table(self):
        aid = self.new(2000)["authorization_id"]
        for body in ({"amount": 0}, {"amount": -5}, {"amount": 1.5}, {"amount": "5"},
                     {"amount": True}, {"amount": None}):
            r = self.capture(aid, body)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), body)
        for final in ("yes", 1, None, [True]):
            r = self.capture(aid, {"final": final})
            self.assertEqual((r.status, r.code), (400, "malformed_request"), final)
        r = self.capture(aid, {"amount": 2001})
        self.assertEqual((r.status, r.code), (422, "capture_exceeds_authorization"))
        self.assertEqual(self.capture(aid, tok=self.ada).code, "forbidden")  # payer
        self.assertEqual(self.capture(aid, tok=self.cy).code, "forbidden")   # neither party
        r = self.capture("a_nope")
        self.assertEqual((r.status, r.code), (404, "not_found"))
        self.assertEqual(me(self.ada)["held"], 2000)
        r = call("POST", "/authorizations/%s/capture" % aid, {}, token=self.bob)
        self.assertEqual(r.code, "missing_idempotency_key")

    def test_expired_capture_is_409_expired(self):
        aid = self.new(2000)["authorization_id"]
        self.capture(aid, {"amount": 500, "final": False})
        self.advance(600)
        r = self.capture(aid)
        self.assertEqual((r.status, r.code), (409, "authorization_expired"))
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"],
                          len(a["payment_ids"])), ("expired", 500, 0, 1))
        ada = me(self.ada)
        self.assertEqual((ada["total"], ada["held"], ada["available"]), (9500, 0, 9500))

    def test_seeded_open_with_nothing_left_is_not_open(self):
        reset(fixture(hold("a_9", amount=500, captured_amount=500)))
        r = call("POST", "/authorizations/a_9/capture", {}, token=token("bob@example.com"),
                 key=key())
        self.assertEqual((r.status, r.code), (409, "authorization_not_open"))

    def test_replay_rules(self):
        aid = self.new(2000)["authorization_id"]
        k = key()
        first = self.capture(aid, {}, k=k)
        again = self.capture(aid, {}, k=k)
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(first.body, again.body)
        self.assertEqual(self.capture(aid, {"amount": 2000}, k=k).code, "idempotency_key_reuse")
        self.assertEqual(me(self.bob)["total"], 4500)
        self.assertEqual(self.capture(aid, {}, k=key()).code, "authorization_not_open")

    def test_concurrent_captures_never_exceed(self):
        aid = self.new(2000)["authorization_id"]
        results = []

        def go():
            results.append(self.capture(aid, {"amount": 300, "final": False}))
        threads = [threading.Thread(target=go) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ok = [r for r in results if r.status == 201]
        self.assertEqual(len(ok), 6)
        self.assertTrue(all(r.code == "capture_exceeds_authorization"
                            for r in results if r.status != 201))
        a = self.view(aid)
        self.assertEqual((a["status"], a["captured_amount"], a["remaining_amount"]),
                         ("open", 1800, 200))
        ada, bob = me(self.ada), me(self.bob)
        self.assertEqual((ada["total"], ada["held"], bob["total"]), (8200, 200, 4300))
        self.assertEqual(ada["total"] + bob["total"] + me(self.cy)["total"], 12500)


class VoidTest(Base):
    def void(self, aid, tok=None):
        return call("POST", "/authorizations/%s/void" % aid, token=tok or self.ada)

    def test_void_releases_and_repeats(self):
        aid = self.new(2000)["authorization_id"]
        self.assertEqual(self.void(aid, tok=self.bob).code, "forbidden")
        self.assertEqual(self.void(aid, tok=self.cy).code, "forbidden")
        r = self.void(aid)
        self.assertEqual((r.status, r.body["status"], r.body["remaining_amount"]),
                         (200, "voided", 0))
        self.assertEqual(set(r.body), VIEW_KEYS)
        self.assertEqual(me(self.ada)["available"], 10000)
        again = self.void(aid)
        self.assertEqual((again.status, again.body), (200, r.body))
        c = call("POST", "/authorizations/%s/capture" % aid, {}, token=self.bob, key=key())
        self.assertEqual((c.status, c.code), (409, "authorization_not_open"))

    def test_void_after_partial_capture_keeps_captures(self):
        aid = self.new(2000)["authorization_id"]
        p = call("POST", "/authorizations/%s/capture" % aid, {"amount": 400, "final": False},
                 token=self.bob, key=key()).body
        r = self.void(aid)
        self.assertEqual((r.body["status"], r.body["captured_amount"], r.body["payment_ids"]),
                         ("voided", 400, [p["payment_id"]]))
        ada = me(self.ada)
        self.assertEqual((ada["total"], ada["held"]), (9600, 0))

    def test_captured_or_expired_is_not_open(self):
        aid = self.new(2000)["authorization_id"]
        call("POST", "/authorizations/%s/capture" % aid, {}, token=self.bob, key=key())
        self.assertEqual(self.void(aid).code, "authorization_not_open")
        aid2 = self.new(100)["authorization_id"]
        self.advance(600)
        r = self.void(aid2)
        self.assertEqual((r.status, r.code), (409, "authorization_not_open"))

    def test_unknown_and_body(self):
        self.assertEqual(self.void("a_nope").code, "not_found")
        aid = self.new(1)["authorization_id"]
        r = call("POST", "/authorizations/%s/void" % aid, raw="{bad", token=self.ada)
        self.assertEqual(r.code, "malformed_request")
        self.assertEqual(call("POST", "/authorizations/%s/void" % aid).status, 401)


if __name__ == "__main__":
    unittest.main()
