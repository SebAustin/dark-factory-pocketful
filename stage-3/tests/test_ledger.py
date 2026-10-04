"""S3.1: bitemporal foundation — revisions, openings, seeded history, hold events."""
import copy
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from harness import FIXTURE, call, reset
from test_holds import ClockCase, fixture, hold
from test_payments import token

from app import instants
from app.store import STORE


def key():
    return uuid.uuid4().hex


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def payments():
    with STORE.lock:
        return copy.deepcopy(STORE.state["payments"])


def users():
    with STORE.lock:
        return copy.deepcopy(STORE.state["users"])


def auths():
    with STORE.lock:
        return copy.deepcopy(STORE.state["authorizations"])


def assert_rev1(test, p):
    test.assertEqual(p["revisions"], [{"revision": 1, "amount": p["amount"],
                                       "effective_at": p["created_at"],
                                       "recorded_at": p["created_at"], "reason": ""}])


class RevisionOneTest(unittest.TestCase):
    def setUp(self):
        f = copy.deepcopy(FIXTURE)
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))

    def test_every_payment_path_writes_revision_one(self):
        made = []
        made.append(call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=self.ada,
                         key=key()).body["payment_id"])
        rq = call("POST", "/requests", {"payer_handle": "ada", "amount": 20}, token=self.bob,
                  key=key()).body["request_id"]
        made.append(call("POST", "/requests/%s/pay" % rq, {}, token=self.ada,
                         key=key()).body["payment_id"])
        st = call("POST", "/settlements", {"transfers": [
            {"from_handle": "ada", "to_handle": "cy", "amount": 30}]}, token=self.cy, key=key())
        made.append(st.body["payments"][0]["payment_id"])
        aid = call("POST", "/authorizations", {"to_handle": "bob", "amount": 40}, token=self.ada,
                   key=key()).body["authorization_id"]
        made.append(call("POST", "/authorizations/%s/capture" % aid, {}, token=self.bob,
                         key=key()).body["payment_id"])
        ps = payments()
        for pid in made + ["p_1"]:
            assert_rev1(self, ps[pid])
        self.assertEqual(ps[made[2]]["created_at"], st.body["committed_at"])

    def test_server_instants_are_microsecond_and_strictly_increasing(self):
        ids = [call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada,
                    key=key()).body for _ in range(5)]
        stamps = [p["created_at"] for p in ids]
        for s in stamps:
            self.assertRegex(s, r"\.\d{6}\+00:00$")
        ks = [instants.key(s) for s in stamps]
        self.assertEqual(ks, sorted(set(ks)))


class OpeningTest(unittest.TestCase):
    def test_openings_from_seeded_history(self):
        reset()
        u = users()
        self.assertEqual((u["u_ada"]["opening"], u["u_bob"]["opening"], u["u_cy"]["opening"]),
                         (10500, 2000, 0))
        r = call("POST", "/auth/signup", {"email": "new@example.com", "password": "password1",
                                          "display_name": "N"})
        self.assertEqual(users()[r.body["user_id"]]["opening"], 0)

    def test_later_payments_do_not_change_openings(self):
        reset()
        call("POST", "/payments", {"to_handle": "cy", "amount": 100},
             token=token("ada@example.com"), key=key())
        self.assertEqual(users()["u_ada"]["opening"], 10500)


class SeededHistoryTest(unittest.TestCase):
    def test_future_created_at_is_422_unchanged(self):
        reset()
        f = copy.deepcopy(FIXTURE)
        f["payments"][0]["created_at"] = (datetime.now(timezone.utc)
                                          + timedelta(hours=1)).isoformat()
        r = call("POST", "/_test/reset", f)
        self.assertEqual((r.status, r.code), (422, "validation_failed"))
        self.assertEqual(users()["u_ada"]["opening"], 10500)

    def test_supplied_created_at_is_revision_one(self):
        f = copy.deepcopy(FIXTURE)
        f["payments"][0]["created_at"] = "2026-09-24T19:00:00+02:00"
        reset(f)
        p = payments()["p_1"]
        self.assertEqual(p["created_at"], "2026-09-24T19:00:00+02:00")
        assert_rev1(self, p)

    def test_omitted_created_at_precedes_api_payments(self):
        reset()
        seeded = instants.key(payments()["p_1"]["created_at"])
        made = call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                    token=token("ada@example.com"), key=key()).body
        self.assertLess(seeded, instants.key(made["created_at"]))

    def test_inconsistent_history_is_422(self):
        f = copy.deepcopy(FIXTURE)
        # cy ends at 0 but pays 100 first and only then receives 100: negative in between.
        f["payments"] = [
            {"id": "p_a", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 100,
             "created_at": ago(7200)},
            {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100,
             "created_at": ago(3600)}]
        r = call("POST", "/_test/reset", f)
        self.assertEqual((r.status, r.code), (422, "validation_failed"), r.raw)
        f["payments"][0]["created_at"], f["payments"][1]["created_at"] = ago(3600), ago(7200)
        self.assertEqual(call("POST", "/_test/reset", f).status, 204)

    def test_same_instant_movements_are_combined(self):
        f = copy.deepcopy(FIXTURE)
        same = ago(3600)
        f["payments"] = [
            {"id": "p_a", "from_user_id": "u_cy", "to_user_id": "u_bob", "amount": 100,
             "created_at": same},
            {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 100,
             "created_at": same}]
        self.assertEqual(call("POST", "/_test/reset", f).status, 204)


class HoldEventsTest(ClockCase):
    def setUp(self):
        super().setUp()
        reset(fixture())
        self.ada, self.bob = token("ada@example.com"), token("bob@example.com")

    def authorize(self, amount=2000):
        return call("POST", "/authorizations", {"to_handle": "bob", "amount": amount},
                    token=self.ada, key=key()).body

    def test_lifecycle_events_and_closed_at(self):
        a = self.authorize()
        self.assertIsNone(a["closed_at"])
        aid = a["authorization_id"]
        c1 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 500, "final": False},
                  token=self.bob, key=key()).body
        c2 = call("POST", "/authorizations/%s/capture" % aid, {"amount": 300}, token=self.bob,
                  key=key()).body
        ev = auths()[aid]["events"]
        self.assertEqual([(e["kind"], e["held_delta"], e["at"]) for e in ev],
                         [("created", 2000, a["created_at"]),
                          ("capture", -500, c1["created_at"]),
                          ("capture", -300, c2["created_at"]),
                          ("release", -1200, c2["created_at"])])
        self.assertEqual(auths()[aid]["closed_at"], c2["created_at"])

    def test_void_and_expiry(self):
        v = self.authorize(100)
        voided = call("POST", "/authorizations/%s/void" % v["authorization_id"],
                      token=self.ada).body
        self.assertIsNotNone(voided["closed_at"])
        ev = auths()[v["authorization_id"]]["events"]
        self.assertEqual((ev[-1]["kind"], ev[-1]["held_delta"], ev[-1]["at"]),
                         ("release", -100, voided["closed_at"]))
        e = self.authorize(50)
        self.advance(600)
        call("GET", "/me", token=self.ada)
        a = auths()[e["authorization_id"]]
        self.assertEqual((a["status"], a["closed_at"], a["events"][-1]["at"],
                          a["events"][-1]["held_delta"]),
                         ("expired", e["expires_at"], e["expires_at"], -50))

    def test_seeded_holds(self):
        reset(fixture(hold("a_1", amount=300), hold("a_2", status="voided"),
                      hold("a_3", amount=10, expires=-3600)))
        a = auths()
        self.assertEqual([e["kind"] for e in a["a_1"]["events"]], ["created"])
        self.assertIsNone(a["a_1"]["closed_at"])
        self.assertEqual(a["a_2"]["events"], [])
        self.assertEqual(a["a_3"]["status"], "expired")
        self.assertEqual(a["a_3"]["closed_at"], a["a_3"]["expires_at"])


class SeededClosedAtTest(unittest.TestCase):
    def test_closed_at_fallbacks(self):  # D-51
        made, closed = ago(7200), ago(3600)
        reset(fixture(hold("a_1", status="captured", closed_at=closed),
                      hold("a_2", status="expired", expires=-60),
                      hold("a_3", status="voided", created_at=made),
                      hold("a_4", status="voided")))
        a = auths()
        self.assertEqual(a["a_1"]["closed_at"], closed)
        self.assertEqual(a["a_2"]["closed_at"], a["a_2"]["expires_at"])
        self.assertEqual(a["a_3"]["closed_at"], made)
        self.assertIsNotNone(instants.key(a["a_4"]["closed_at"]))

    def test_future_created_at_on_requests_and_holds_is_422(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        f = copy.deepcopy(FIXTURE)
        f["requests"][0]["created_at"] = future
        self.assertEqual(call("POST", "/_test/reset", f).status, 422)
        self.assertEqual(call("POST", "/_test/reset", fixture(hold(created_at=future))).status,
                         422)


class ExportRoundTripTest(unittest.TestCase):
    def test_stage3_round_trip_is_stable(self):
        reset()
        ada = token("ada@example.com")
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada, key=key())
        first = call("GET", "/_test/export").body
        self.assertEqual(call("POST", "/_test/import", first).status, 204)
        self.assertEqual(call("GET", "/_test/export").body, first)
        made = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada,
                    key=key()).body
        self.assertGreater(instants.key(made["created_at"]),
                           max(instants.key(p["created_at"])
                               for p in first["state"]["payments"].values()))


if __name__ == "__main__":
    unittest.main()
