import copy
import threading
import unittest
import uuid

from harness import FIXTURE, call, reset

from app.store import STORE


def token(email):
    r = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert r.status == 200, r.raw
    return r.body["token"]


def balances():
    with STORE.lock:
        return {u["handle"]: u["balance"] for u in STORE.state["users"].values()}


def key():
    return uuid.uuid4().hex


def pay(tok, body, k=None, raw=None):
    return call("POST", "/payments", body, token=tok, key=k or key(), raw=raw)


class PaymentTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")
        self.bob = token("bob@example.com")
        self.cy = token("cy@example.com")

    def test_201_shape_and_balances(self):
        r = pay(self.ada, {"to_handle": "bob", "amount": 1500, "note": "dinner",
                           "visibility": "public"})
        self.assertEqual(r.status, 201, r.raw)
        b = r.body
        self.assertEqual(b["from_user_id"], "u_ada")
        self.assertEqual(b["from_handle"], "ada")
        self.assertEqual(b["to_user_id"], "u_bob")
        self.assertEqual(b["to_handle"], "bob")
        self.assertEqual((b["amount"], b["currency"], b["note"], b["visibility"]),
                         (1500, "EUR", "dinner", "public"))
        self.assertIsNone(b["request_id"])
        self.assertIsNone(b["settlement_id"])
        self.assertRegex(b["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$")
        self.assertTrue(b["payment_id"] and len(b["payment_id"]) <= 64)
        self.assertNotEqual(b["payment_id"], "p_1")
        self.assertEqual(balances(), {"ada": 8500, "bob": 4000, "cy": 0})

    def test_defaults(self):
        r = pay(self.ada, {"to_handle": "bob", "amount": 1})
        self.assertEqual((r.body["note"], r.body["visibility"]), ("", "public"))

    def test_amount_number_forms(self):
        for raw in ('1000', '1000.0', '1e3', '1E3', '10000e-1'):
            r = pay(self.ada, None, raw='{"to_handle":"bob","amount":%s}' % raw)
            self.assertEqual(r.status, 201, (raw, r.raw))
            self.assertEqual(r.body["amount"], 1000)

    def test_invalid_amounts_422(self):
        for amount in (0, -1, 1000000001, 1.5, "100", True, False, None, [1], {"a": 1}):
            r = pay(self.ada, {"to_handle": "bob", "amount": amount})
            self.assertEqual((r.status, r.code), (422, "validation_failed"), amount)
        for raw in ('1000.0000000001', '1e400'):
            r = pay(self.ada, None, raw='{"to_handle":"bob","amount":%s}' % raw)
            self.assertEqual(r.status, 422, raw)
        r = pay(self.ada, {"to_handle": "bob"})
        self.assertEqual(r.status, 422)
        self.assertEqual(balances()["ada"], 10000)

    def test_max_amount_accepted(self):
        f = copy.deepcopy(FIXTURE)
        f["users"][0]["balance"] = 2000000000
        reset(f)
        r = pay(token("ada@example.com"), {"to_handle": "bob", "amount": 1000000000})
        self.assertEqual(r.status, 201)

    def test_insufficient_funds_changes_nothing(self):
        r = pay(self.cy, {"to_handle": "ada", "amount": 1})
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))
        r = pay(self.bob, {"to_handle": "ada", "amount": 2501})
        self.assertEqual(r.code, "insufficient_funds")
        self.assertEqual(pay(self.bob, {"to_handle": "ada", "amount": 2500}).status, 201)
        self.assertEqual(balances()["bob"], 0)

    def test_self_payment(self):
        r = pay(self.ada, {"to_handle": "ada", "amount": 1})
        self.assertEqual((r.status, r.code), (422, "self_payment"))

    def test_unknown_handle_404(self):
        r = pay(self.ada, {"to_handle": "nobody", "amount": 1})
        self.assertEqual((r.status, r.code), (404, "not_found"))

    def test_note_rules(self):
        self.assertEqual(pay(self.ada, {"to_handle": "bob", "amount": 1,
                                        "note": "x" * 200}).status, 201)
        for note in ("x" * 201, None, 5, ["a"]):
            r = pay(self.ada, {"to_handle": "bob", "amount": 1, "note": note})
            self.assertEqual((r.status, r.code), (422, "validation_failed"), note)

    def test_note_verbatim_unicode(self):
        note = "  Café 🍕\n<b>&amp;</b> \"q\" \u200b "
        r = pay(self.ada, {"to_handle": "bob", "amount": 1, "note": note})
        self.assertEqual(r.body["note"], note)
        feed = call("GET", "/activity", token=self.bob).body["payments"]
        self.assertEqual(feed[0]["note"], note)

    def test_visibility_rules(self):
        for vis in ("PUBLIC", "friends", None, 1, True, ""):
            r = pay(self.ada, {"to_handle": "bob", "amount": 1, "visibility": vis})
            self.assertEqual((r.status, r.code), (422, "validation_failed"), vis)

    def test_wrong_type_handle_400_missing_422(self):
        r = pay(self.ada, {"to_handle": 7, "amount": 1})
        self.assertEqual((r.status, r.code), (400, "malformed_request"))
        r = pay(self.ada, {"amount": 1})
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_auth_required(self):
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, key=key())
        self.assertEqual(r.status, 401)


class IdempotencyTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")
        self.cy = token("cy@example.com")
        self.body = {"to_handle": "bob", "amount": 100, "note": "n", "visibility": "public"}

    def test_missing_or_empty_key_400(self):
        r = call("POST", "/payments", self.body, token=self.ada)
        self.assertEqual((r.status, r.code), (400, "missing_idempotency_key"))
        r = call("POST", "/payments", self.body, token=self.ada, key="")
        self.assertEqual(r.code, "missing_idempotency_key")

    def test_key_length(self):
        self.assertEqual(pay(self.ada, self.body, k="x" * 255).status, 201)
        r = pay(self.ada, self.body, k="y" * 256)
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_replay_returns_200_identical_body_moves_once(self):
        k = key()
        first = pay(self.ada, self.body, k)
        again = pay(self.ada, None, k, raw='{ "visibility":"public","note":"n",'
                                          '"amount":1e2, "to_handle":"bob" }')
        self.assertEqual(first.status, 201)
        self.assertEqual(again.status, 200)
        self.assertEqual(again.body, first.body)
        self.assertEqual(balances()["ada"], 9900)

    def test_different_body_409(self):
        k = key()
        pay(self.ada, self.body, k)
        r = pay(self.ada, dict(self.body, amount=101), k)
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))
        r = pay(self.ada, {k_: v for k_, v in self.body.items() if k_ != "visibility"}, k)
        self.assertEqual(r.code, "idempotency_key_reuse")

    def test_claimed_key_resolved_before_validation(self):
        k = key()
        pay(self.ada, self.body, k)
        r = pay(self.ada, {"to_handle": "nobody", "amount": -5}, k)
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))

    def test_true_is_not_one(self):
        k = key()
        pay(self.ada, {"to_handle": "bob", "amount": 1}, k)
        r = pay(self.ada, {"to_handle": "bob", "amount": True}, k)
        self.assertEqual(r.code, "idempotency_key_reuse")

    def test_failed_key_is_reusable(self):
        k = key()
        self.assertEqual(pay(self.ada, dict(self.body, amount=0), k).status, 422)
        self.assertEqual(pay(self.cy, self.body, k).status, 409)  # cy has 0
        self.assertEqual(pay(self.ada, self.body, k).status, 201)

    def test_key_scoped_per_user(self):
        k = key()
        self.assertEqual(pay(self.ada, self.body, k).status, 201)
        f_bob = token("bob@example.com")
        r = pay(f_bob, dict(self.body, to_handle="ada"), k)
        self.assertEqual(r.status, 201)

    def test_replay_after_state_change_still_original(self):
        k = key()
        first = pay(self.ada, dict(self.body, amount=10000), k)
        self.assertEqual(first.status, 201)
        again = pay(self.ada, dict(self.body, amount=10000), k)
        self.assertEqual((again.status, again.body), (200, first.body))

    def test_concurrent_identical_exactly_one_201(self):
        k = key()
        results = []

        def go():
            results.append(pay(self.ada, self.body, k))
        threads = [threading.Thread(target=go) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        statuses = sorted(r.status for r in results)
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertEqual(statuses.count(200), 29)
        bodies = {str(sorted(r.body.items())) for r in results}
        self.assertEqual(len(bodies), 1)
        self.assertEqual(balances()["ada"], 9900)

    def test_concurrent_drain_never_negative(self):
        f = copy.deepcopy(FIXTURE)
        f["users"][2]["balance"] = 1000
        reset(f)
        cy = token("cy@example.com")
        results = []

        def go(i):
            results.append(pay(cy, {"to_handle": "ada" if i % 2 else "bob", "amount": 100}))
        threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r.status == 201 for r in results), 10)
        self.assertTrue(all(r.status in (201, 409) for r in results))
        b = balances()
        self.assertEqual(b["cy"], 0)
        self.assertEqual(sum(b.values()), 13500)


class ActivityTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")
        self.bob = token("bob@example.com")
        self.cy = token("cy@example.com")

    def feed(self, tok, query=""):
        r = call("GET", "/activity" + query, token=tok)
        self.assertEqual(r.status, 200, r.raw)
        return r.body

    def test_feed_rule(self):
        priv = pay(self.ada, {"to_handle": "bob", "amount": 5, "visibility": "private"}).body
        pub = pay(self.bob, {"to_handle": "ada", "amount": 6}).body
        ids = lambda tok: [p["payment_id"] for p in self.feed(tok)["payments"]]
        self.assertEqual(ids(self.ada), [pub["payment_id"], priv["payment_id"], "p_1"])
        self.assertEqual(ids(self.bob), [pub["payment_id"], priv["payment_id"], "p_1"])
        self.assertEqual(ids(self.cy), [pub["payment_id"], "p_1"])
        bob_view = self.feed(self.bob)["payments"][1]
        self.assertEqual(bob_view, priv)

    def test_requests_never_in_feed(self):
        self.assertTrue(all("payment_id" in p for p in self.feed(self.ada)["payments"]))
        self.assertEqual(len(self.feed(self.ada)["payments"]), 1)

    def test_pagination(self):
        for i in range(5):
            pay(self.ada, {"to_handle": "bob", "amount": 1, "note": str(i)})
        page = self.feed(self.cy, "?limit=2&offset=0")
        self.assertEqual([p["note"] for p in page["payments"]], ["4", "3"])
        self.assertTrue(page["has_more"])
        page = self.feed(self.cy, "?limit=2&offset=5")
        self.assertEqual([p["note"] for p in page["payments"]], ["coffee"])
        self.assertFalse(page["has_more"])
        page = self.feed(self.cy, "?limit=6")
        self.assertFalse(page["has_more"])
        self.assertEqual(self.feed(self.cy, "?offset=99")["payments"], [])
        self.assertEqual(len(self.feed(self.cy, "?limit=200&unknown=x")["payments"]), 6)

    def test_bad_query_422(self):
        for q in ("limit=0", "limit=201", "limit=1e9", "limit=4.0", "limit=+4", "limit=-1",
                  "limit=", "offset=-1", "offset=abc", "offset=1.0"):
            r = call("GET", "/activity?" + q, token=self.ada)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), q)

    def test_auth_required(self):
        self.assertEqual(call("GET", "/activity").status, 401)


if __name__ == "__main__":
    unittest.main()


class InstantOrderTest(unittest.TestCase):
    """F2: newest first by created_at means by instant, whatever the offset."""

    def fixture(self):
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [
            {"id": "p_east", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
             "note": "17:00Z", "visibility": "public",
             "created_at": "2026-09-24T19:00:00+02:00"},
            {"id": "p_utc", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
             "note": "18:30Z", "visibility": "public",
             "created_at": "2026-09-24T18:30:00+00:00"},
            {"id": "p_west", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
             "note": "18:45Z", "visibility": "public",
             "created_at": "2026-09-24T13:45:00-05:00"},
        ]
        return f

    def test_activity_orders_by_instant_and_keeps_offsets(self):
        reset(self.fixture())
        feed = call("GET", "/activity", token=token("cy@example.com")).body["payments"]
        self.assertEqual([p["payment_id"] for p in feed], ["p_west", "p_utc", "p_east"])
        self.assertEqual(feed[2]["created_at"], "2026-09-24T19:00:00+02:00")

    def test_new_payment_is_newest(self):
        reset(self.fixture())
        ada = token("ada@example.com")
        made = pay(ada, {"to_handle": "bob", "amount": 1}).body
        feed = call("GET", "/activity", token=ada).body["payments"]
        self.assertEqual(feed[0]["payment_id"], made["payment_id"])

    def test_invalid_fixture_created_at_is_422(self):
        for bad in ("yesterday", "2026-09-24T18:30:00", "2026-09-24", "2026-13-01T00:00:00Z",
                    5, True, "2026-09-24 18:30:00+00:00"):
            f = self.fixture()
            f["payments"][0]["created_at"] = bad
            r = call("POST", "/_test/reset", f)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), bad)
            f = self.fixture()
            f["requests"][0]["created_at"] = bad
            r = call("POST", "/_test/reset", f)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), bad)

    def test_lowercase_t_and_z_accepted(self):
        f = self.fixture()
        f["payments"][1]["created_at"] = "2026-09-24t18:30:00z"
        reset(f)
        feed = call("GET", "/activity", token=token("cy@example.com")).body["payments"]
        self.assertEqual(feed[1]["created_at"], "2026-09-24t18:30:00z")  # verbatim (D-41)

    def test_z_suffix_accepted_and_kept_as_received(self):
        f = self.fixture()
        f["payments"][1]["created_at"] = "2026-09-24T18:30:00Z"
        reset(f)
        feed = call("GET", "/activity", token=token("cy@example.com")).body["payments"]
        self.assertEqual(feed[1]["created_at"], "2026-09-24T18:30:00Z")  # D-41
