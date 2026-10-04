"""S3.2: GET /me?as_of=&known_at= (stage 3; D-43, D-48, D-51)."""
import copy
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from harness import FIXTURE, call, reset
from test_holds import ClockCase, hold
from test_payments import token

from app import instants


def iso(dt):
    return dt.isoformat(timespec="microseconds")


def shift(text, micros):
    return iso(instants.parse(text) + timedelta(microseconds=micros))


def me(tok, **params):
    q = "&".join("{}={}".format(k, quote(v, safe="")) for k, v in params.items())
    r = call("GET", "/me" + ("?" + q if q else ""), token=tok)
    return r


class Base(ClockCase):
    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)
        self.t1 = iso(now - timedelta(hours=3))
        self.t2 = iso(now - timedelta(hours=2))
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
             "note": "coffee", "visibility": "public", "created_at": self.t1},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 300,
             "created_at": self.t2}]
        f["users"][1]["balance"] = 2200   # bob: 2000 + 500 - 300
        f["users"][2]["balance"] = 300    # cy: 0 + 300
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))

    def money(self, tok, **params):
        r = me(tok, **params)
        self.assertEqual(r.status, 200, r.raw)
        return r.body


class AsOfTest(Base):
    def test_inclusive_boundaries_opening_and_current(self):
        self.assertEqual(self.money(self.ada, as_of=shift(self.t1, -1))["balance"], 10500)
        self.assertEqual(self.money(self.ada, as_of=self.t1)["balance"], 10000)  # inclusive
        self.assertEqual(self.money(self.bob, as_of=self.t1)["balance"], 2500)
        self.assertEqual(self.money(self.bob, as_of=self.t2)["balance"], 2200)
        self.assertEqual(self.money(self.bob, as_of="1970-01-01T00:00:00Z")["balance"], 2000)
        self.assertEqual(self.money(self.bob, as_of="2999-01-01T00:00:00Z")["balance"], 2200)

    def test_offsets_and_fractions_are_the_same_instant(self):
        t = instants.parse(self.t1)
        east = (t.astimezone(timezone(timedelta(hours=2)))).isoformat(timespec="microseconds")
        nanos = self.t1.replace("+00:00", "000+00:00")
        for form in (east, nanos, self.t1.replace("+00:00", "Z")):
            self.assertEqual(self.money(self.ada, as_of=form)["balance"], 10000, form)

    def test_shape_and_echo(self):
        plain = self.money(self.ada)
        self.assertEqual(list(plain), ["user_id", "display_name", "handle", "balance", "total",
                                       "available", "held", "currency", "minor_units"])
        given = "2026-09-24T19:00:00.5+02:00"
        body = self.money(self.ada, as_of=given, known_at="2999-01-01t00:00:00z")
        self.assertEqual((body["as_of"], body["known_at"]), (given, "2999-01-01t00:00:00z"))
        self.assertEqual(body["balance"], body["total"])
        self.assertNotIn("known_at", self.money(self.ada, as_of=given))

    def test_unencoded_plus_is_repaired_and_echoed_as_received(self):
        raw = self.t1.replace("+00:00", "+00:00")
        r = call("GET", "/me?as_of=" + raw, token=self.ada)  # '+' decodes to a space
        self.assertEqual(r.status, 200, r.raw)
        self.assertEqual(r.body["balance"], 10000)
        self.assertEqual(r.body["as_of"], raw.replace("+", " "))

    def test_invalid_instants_are_422(self):
        for bad in ("2026-09-24T13:20:00", "2026-09-24", "", "yesterday", "1727184000",
                    "2026-09-24 13:20:00Z", "2026-09-24T13:20:00.1234567891Z",
                    "2026-09-24T13:20:00+24:00", "2026-02-30T00:00:00Z"):
            for name in ("as_of", "known_at"):
                r = me(self.ada, **{name: bad})
                self.assertEqual((r.status, r.code), (422, "validation_failed"), (name, bad))

    def test_sum_of_totals_constant_in_every_view(self):
        toks = (self.ada, self.bob, self.cy)
        for t in ("1970-01-01T00:00:00Z", shift(self.t1, -1), self.t1, self.t2,
                  "2999-01-01T00:00:00Z"):
            self.assertEqual(sum(self.money(tok, as_of=t)["total"] for tok in toks), 12500, t)


class KnownAtTest(Base):
    def test_payment_not_yet_recorded_contributes_nothing(self):
        before = iso(datetime.now(timezone.utc))
        made = call("POST", "/payments", {"to_handle": "bob", "amount": 100}, token=self.ada,
                    key=uuid.uuid4().hex).body
        self.assertEqual(self.money(self.ada, known_at=before)["balance"], 10000)
        self.assertEqual(self.money(self.ada, known_at=made["created_at"])["balance"], 9900)
        self.assertEqual(self.money(self.ada, known_at=shift(made["created_at"], -1))[
            "balance"], 10000)
        self.assertEqual(self.money(self.ada)["balance"], 9900)
        self.assertEqual(self.money(self.ada, known_at=self.t1, as_of=self.t1)["balance"],
                         10000)
        self.assertEqual(self.money(self.ada, known_at=shift(self.t1, -1),
                                    as_of="2999-01-01T00:00:00Z")["balance"], 10500)


class HeldHistoryTest(Base):
    def authorize(self, amount, ttl=None):
        return call("POST", "/authorizations", {"to_handle": "bob", "amount": amount},
                    token=self.ada, key=uuid.uuid4().hex).body

    def test_hold_lifecycle_across_as_of_and_known_at(self):
        a = self.authorize(2000)
        c = a["created_at"]
        cap = call("POST", "/authorizations/%s/capture" % a["authorization_id"],
                   {"amount": 500, "final": False}, token=self.bob, key=uuid.uuid4().hex).body
        e = cap["created_at"]
        view = lambda **kw: self.money(self.ada, **kw)
        self.assertEqual(view(as_of=shift(c, -1))["held"], 0)
        v = view(as_of=c)
        self.assertEqual((v["held"], v["total"], v["available"]), (2000, 10000, 8000))
        v = view(as_of=e)
        self.assertEqual((v["held"], v["total"], v["available"]), (1500, 9500, 8000))
        v = view(as_of=e, known_at=shift(e, -1))  # capture not known yet
        self.assertEqual((v["held"], v["total"]), (2000, 10000))
        self.assertEqual(view(known_at=shift(c, -1))["held"], 0)  # creation unknown
        v = view(as_of=a["expires_at"])  # expiry known once creation is known
        self.assertEqual((v["held"], v["available"]), (0, v["total"]))
        v = view(as_of=shift(a["expires_at"], -1))
        self.assertEqual(v["held"], 1500)
        current = view()
        self.assertEqual((current["held"], current["available"]), (1500, 8000))

    def test_void_known_only_after_it_happened(self):
        a = self.authorize(700)
        void = call("POST", "/authorizations/%s/void" % a["authorization_id"],
                    token=self.ada).body
        v_at = void["closed_at"]
        self.assertEqual(self.money(self.ada, as_of=v_at)["held"], 0)
        self.assertEqual(self.money(self.ada, as_of=shift(v_at, -1))["held"], 700)
        self.assertEqual(self.money(self.ada, as_of=v_at, known_at=shift(v_at, -1))["held"], 700)

    def test_clock_expiry_in_the_future_view(self):
        reset_fixture = copy.deepcopy(FIXTURE)
        reset_fixture["authorizations"] = [hold("a_1", amount=300, expires=7200)]
        reset(reset_fixture)
        ada = token("ada@example.com")
        self.assertEqual(self.money(ada)["held"], 300)
        far = self.money(ada, as_of="2999-01-01T00:00:00Z")
        self.assertEqual((far["held"], far["available"]), (0, far["total"]))


class CurrentEqualsViewTest(Base):
    def test_view_at_now_matches_stored_values_after_every_write_kind(self):
        from test_ledger import key
        f = copy.deepcopy(FIXTURE)
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        ada, bob, cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))
        call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=ada, key=key())
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 20}, token=bob,
                  key=key()).body["request_id"]
        call("POST", "/requests/%s/pay" % rq, {}, token=ada, key=key())
        call("POST", "/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy",
                                                     "amount": 5}]}, token=cy, key=key())
        a = call("POST", "/authorizations", {"to_handle": "bob", "amount": 300}, token=ada,
                 key=key()).body["authorization_id"]
        call("POST", "/authorizations/%s/capture" % a, {"amount": 100, "final": False},
             token=bob, key=key())
        v = call("POST", "/authorizations", {"to_handle": "cy", "amount": 50}, token=ada,
                 key=key()).body["authorization_id"]
        call("POST", "/authorizations/%s/void" % v, token=ada)
        for tok in (ada, bob, cy):
            stored = self.money(tok)
            view = self.money(tok, known_at="2999-01-01T00:00:00Z")
            for field in ("balance", "total", "available", "held"):
                self.assertEqual(view[field], stored[field], field)


if __name__ == "__main__":
    unittest.main()
