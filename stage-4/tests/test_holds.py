"""S2.2: holds model — seeded holds, held/available, clock expiry, available-based refusals."""
import copy
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from harness import FIXTURE, call, reset
from test_payments import token

from app import store
from app.store import STORE


def at(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def hold(aid="a_1", frm="u_ada", to="u_bob", amount=2000, status="open", expires=3600, **extra):
    return {"id": aid, "from_user_id": frm, "to_user_id": to, "amount": amount,
            "note": "deposit", "visibility": "public", "status": status,
            "expires_at": at(expires), **extra}


def fixture(*holds, **top):
    f = copy.deepcopy(FIXTURE)
    f["authorizations"] = list(holds)
    f.update(top)
    return f


def me(tok):
    r = call("GET", "/me", token=tok)
    assert r.status == 200, r.raw
    return r.body


class ClockCase(unittest.TestCase):
    def setUp(self):
        self.saved_clock = store.clock

    def tearDown(self):
        store.clock = self.saved_clock

    def advance(self, seconds):
        base = time.time()
        store.clock = lambda: base + seconds


class MeTest(ClockCase):
    def test_no_holds_all_agree(self):
        reset()
        body = me(token("ada@example.com"))
        self.assertEqual({k: body[k] for k in ("balance", "total", "available", "held")},
                         {"balance": 10000, "total": 10000, "available": 10000, "held": 0})
        self.assertEqual(list(body), ["user_id", "display_name", "handle", "balance", "total",
                                      "available", "held", "currency", "minor_units"])

    def test_seeded_open_hold(self):
        reset(fixture(hold()))
        body = me(token("ada@example.com"))
        self.assertEqual((body["balance"], body["total"], body["available"], body["held"]),
                         (10000, 10000, 8000, 2000))
        self.assertEqual(me(token("bob@example.com"))["held"], 0)

    def test_partially_captured_seed_holds_remainder(self):
        reset(fixture(hold(captured_amount=500)))
        self.assertEqual(me(token("ada@example.com"))["held"], 1500)

    def test_only_open_holds_count(self):
        reset(fixture(hold("a_1", status="captured"), hold("a_2", status="voided"),
                      hold("a_3", status="expired"), hold("a_4", amount=100)))
        self.assertEqual(me(token("ada@example.com"))["held"], 100)

    def test_seeded_open_but_past_is_expired(self):
        reset(fixture(hold(expires=-3600)))
        self.assertEqual(me(token("ada@example.com"))["available"], 10000)
        with STORE.lock:
            self.assertEqual(STORE.state["authorizations"]["a_1"]["status"], "expired")

    def test_clock_expiry_without_any_request_at_the_deadline(self):
        reset(fixture(hold(expires=3600)))
        tok = token("ada@example.com")
        self.assertEqual(me(tok)["held"], 2000)
        self.advance(3600)  # expires_at "at or before now" counts as expired
        body = me(tok)
        self.assertEqual((body["held"], body["available"], body["total"]), (0, 10000, 10000))
        with STORE.lock:
            self.assertEqual(STORE.state["authorizations"]["a_1"]["status"], "expired")


class FixtureTest(unittest.TestCase):
    def assert_rejected(self, f):
        reset()
        r = call("POST", "/_test/reset", f)
        self.assertEqual((r.status, r.code), (422, "validation_failed"), r.raw)
        with STORE.lock:  # unchanged: still the plain fixture
            self.assertEqual(STORE.state["authorizations"], {})
            self.assertEqual(STORE.state["users"]["u_ada"]["balance"], 10000)

    def test_holds_above_balance_rejected(self):
        self.assert_rejected(fixture(hold("a_1", amount=6000), hold("a_2", amount=4001)))
        self.assertEqual(call("POST", "/_test/reset",
                              fixture(hold("a_1", amount=6000), hold("a_2", amount=4000))).status,
                         204)

    def test_expired_or_closed_seeds_do_not_count_toward_balance(self):
        f = fixture(hold("a_1", amount=10000), hold("a_2", amount=9000, expires=-3600),
                    hold("a_3", amount=9000, status="captured"))
        self.assertEqual(call("POST", "/_test/reset", f).status, 204)

    def test_ttl_rules(self):
        for bad in (0, -1, 1.5, "600", True, None, 10 ** 12, 10 ** 30):
            self.assert_rejected(fixture(authorization_ttl_seconds=bad))
        reset(fixture())
        with STORE.lock:
            self.assertEqual(STORE.state["settings"]["authorization_ttl_seconds"], 600)
        reset(fixture(authorization_ttl_seconds=1.0))
        with STORE.lock:
            self.assertEqual(STORE.state["settings"]["authorization_ttl_seconds"], 1)

    def test_large_ttl_up_to_year_9999(self):
        reset(fixture(authorization_ttl_seconds=10 ** 9 + 1))
        from datetime import datetime, timezone
        limit = (datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
                 - datetime.now(timezone.utc)).total_seconds()
        reset(fixture(authorization_ttl_seconds=int(limit) - 60))
        r = call("POST", "/authorizations", {"to_handle": "bob", "amount": 1},
                 token=token("ada@example.com"), key=uuid.uuid4().hex)
        self.assertEqual(r.status, 201, r.raw)
        self.assertTrue(r.body["expires_at"].startswith("9999-12-31T"))
        self.assert_rejected(fixture(authorization_ttl_seconds=int(limit) + 3600))

    def test_authorization_entry_rules(self):
        for h in (hold(frm="u_nobody"), hold(to="u_ada"), hold(status="pending"),
                  hold(amount=0), hold(amount=1000000001), hold(captured_amount=2001),
                  hold(captured_amount=-1), {**hold(), "expires_at": "tomorrow"},
                  {k: v for k, v in hold().items() if k != "expires_at"},
                  {k: v for k, v in hold().items() if k != "status"},
                  hold(visibility="secret"), hold(note=5), hold(aid="")):
            self.assert_rejected(fixture(h))
        self.assert_rejected(fixture(hold("a_1"), hold("a_1")))
        self.assert_rejected({**fixture(), "authorizations": {"a": 1}})

    def test_omitted_authorizations_is_empty(self):
        f = copy.deepcopy(FIXTURE)
        f.pop("authorizations", None)
        reset(f)
        with STORE.lock:
            self.assertEqual(STORE.state["authorizations"], {})


class AvailableRefusalTest(unittest.TestCase):
    def setUp(self):
        f = fixture(hold(amount=2000))
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        self.ada = token("ada@example.com")
        self.bob = token("bob@example.com")
        self.cy = token("cy@example.com")

    def pay(self, amount):
        return call("POST", "/payments", {"to_handle": "bob", "amount": amount},
                    token=self.ada, key=uuid.uuid4().hex)

    def test_payment_against_available(self):
        self.assertEqual(self.pay(8001).code, "insufficient_funds")
        r = self.pay(8000)
        self.assertEqual(r.status, 201)
        self.assertIsNone(r.body["authorization_id"])
        body = me(self.ada)
        self.assertEqual((body["total"], body["available"], body["held"]), (2000, 0, 2000))

    def test_request_pay_against_available(self):
        r = call("POST", "/requests", {"payer_handle": "ada", "amount": 8001}, token=self.bob,
                 key=uuid.uuid4().hex)
        rid = r.body["request_id"]
        r = call("POST", "/requests/%s/pay" % rid, {}, token=self.ada, key=uuid.uuid4().hex)
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))
        self.assertEqual(self.pay(8000).status, 201)

    def test_settlement_net_debit_against_available(self):
        r = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 9000},
            {"from_handle": "bob", "to_handle": "ada", "amount": 500}]},
            token=self.cy, key=uuid.uuid4().hex)
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))  # net -8500 > 8000
        r = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "bob", "amount": 9000},
            {"from_handle": "bob", "to_handle": "ada", "amount": 1000}]},
            token=self.cy, key=uuid.uuid4().hex)
        self.assertEqual(r.status, 201)  # net -8000 == available
        self.assertEqual(me(self.ada)["available"], 0)

    def test_payment_view_has_authorization_id(self):
        r = self.pay(1)
        self.assertEqual(len(r.body), 14)
        feed = call("GET", "/activity", token=self.ada).body["payments"]
        self.assertTrue(all("authorization_id" in p for p in feed))


if __name__ == "__main__":
    unittest.main()
