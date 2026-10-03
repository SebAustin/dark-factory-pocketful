import copy
import unittest

from harness import FIXTURE, call, reset

from app.store import STORE


def total():
    with STORE.lock:
        return sum(u["balance"] for u in STORE.state["users"].values())


class HealthTest(unittest.TestCase):
    def test_health_ok(self):
        r = call("GET", "/health")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, {"status": "ok"})
        self.assertTrue(r.headers["Content-Type"].startswith("application/json; charset=utf-8"))


class ResetTest(unittest.TestCase):
    def test_reset_returns_204_and_loads_fixture(self):
        reset()
        self.assertEqual(total(), 12500)
        with STORE.lock:
            s = STORE.state
            self.assertEqual(s["currency"], "EUR")
            self.assertEqual(s["minor_units"], 2)
            self.assertEqual(s["handles"]["bob"], "u_bob")
            self.assertIn("p_1", s["payments"])
            self.assertEqual(s["requests"]["rq_1"]["status"], "pending")
            self.assertEqual(s["users"]["u_ada"]["balance"], 10000)
            self.assertNotEqual(s["users"]["u_ada"]["password_hash"], "correct horse")

    def test_repeated_reset_replaces_state(self):
        reset()
        small = {"currency": "JPY", "minor_units": 0, "users": [
            {"id": "x", "email": "x@e.com", "password": "password1", "display_name": "X",
             "handle": "x", "balance": 7}]}
        reset(small)
        with STORE.lock:
            self.assertEqual(list(STORE.state["users"]), ["x"])
            self.assertEqual(STORE.state["payments"], {})
        self.assertEqual(total(), 7)

    def test_negative_balance_is_422_and_changes_nothing(self):
        reset()
        bad = copy.deepcopy(FIXTURE)
        bad["users"][1]["balance"] = -1
        r = call("POST", "/_test/reset", bad)
        self.assertEqual(r.status, 422)
        self.assertEqual(r.code, "validation_failed")
        self.assertEqual(total(), 12500)

    def test_invalid_fixture_shapes_are_422(self):
        reset()
        cases = []
        for mutate in (
            lambda f: f.update(minor_units=1),
            lambda f: f.pop("currency"),
            lambda f: f["users"][0].update(handle="Ada"),
            lambda f: f["users"][1].update(handle="ada"),
            lambda f: f["users"][1].update(id="u_ada"),
            lambda f: f["users"][0].update(balance=1.5),
            lambda f: f["users"][0].update(balance=True),
            lambda f: f["payments"][0].update(to_user_id="u_nobody"),
            lambda f: f["requests"][0].update(status="weird"),
            lambda f: f.update(settlement_operator_ids=["u_nobody"]),
        ):
            f = copy.deepcopy(FIXTURE)
            mutate(f)
            cases.append(f)
        for f in cases:
            r = call("POST", "/_test/reset", f)
            self.assertEqual(r.status, 422, (f, r.raw))
            self.assertEqual(r.code, "validation_failed")
        self.assertEqual(total(), 12500)

    def test_seeded_password_hash_verifies(self):
        from app.passwords import verify_password
        reset()
        with STORE.lock:
            stored = STORE.state["users"]["u_bob"]["password_hash"]
        self.assertTrue(verify_password("correct horse", stored))
        self.assertFalse(verify_password("wrong horse", stored))

    def test_large_reset_with_distinct_passwords_within_budget(self):
        import time
        users = [{"id": "u%d" % i, "email": "u%d@e.com" % i, "password": "pw-%d-secret" % i,
                  "display_name": "U", "handle": "h%d" % i, "balance": 1} for i in range(1000)]
        started = time.monotonic()
        reset({"currency": "BHD", "minor_units": 3, "users": users})
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(total(), 1000)

    def test_operators_loaded(self):
        f = copy.deepcopy(FIXTURE)
        f["settlement_operator_ids"] = ["u_cy"]
        reset(f)
        with STORE.lock:
            self.assertEqual(STORE.state["operators"], ["u_cy"])

    def test_malformed_body_is_400(self):
        r = call("POST", "/_test/reset", raw="{not json")
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "malformed_request")
        self.assertIn("message", r.body["error"])

    def test_non_object_body_is_400(self):
        r = call("POST", "/_test/reset", raw="[1,2]")
        self.assertEqual(r.status, 400)


class RoutingTest(unittest.TestCase):
    def test_unknown_route_is_404_envelope(self):
        r = call("GET", "/nope")
        self.assertEqual(r.status, 404)
        self.assertEqual(r.code, "not_found")

    def test_wrong_method_has_envelope(self):
        r = call("DELETE", "/health")
        self.assertEqual(r.status, 405)
        self.assertEqual(r.code, "method_not_allowed")


if __name__ == "__main__":
    unittest.main()
