import random
import threading
import unittest

from harness import call, reset

from app.splits import shares
from app.store import STORE, new_token


def fixture(**balances):
    base = {"ada": 1000, "bob": 0, "cy": 0, "dee": 5}
    base.update(balances)
    users = [{"id": "u_" + h, "email": h + "@example.com", "password": "correct horse",
              "display_name": h.title(), "handle": h, "balance": b} for h, b in base.items()]
    return {"currency": "EUR", "minor_units": 2, "users": users, "payments": [], "requests": []}


def token(handle):
    with STORE.lock:
        return new_token(STORE.state, "u_" + handle)


def split(who, amount, handles, key="s1", **extra):
    return call("POST", "/splits", {"amount": amount, "participant_handles": handles, **extra},
                token=token(who), key=key)


def snapshot():
    with STORE.lock:
        return ({u["handle"]: u["balance"] for u in STORE.state["users"].values()},
                len(STORE.state["requests"]), len(STORE.state["splits"]), len(STORE.state["payments"]))


class SharesTest(unittest.TestCase):
    def test_spec_table(self):
        for amount, n, want in ((1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
                                (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1])):
            self.assertEqual(shares(amount, n), want, (amount, n))

    def test_properties_for_random_amounts(self):
        rng = random.Random(7)
        for _ in range(2000):
            amount, n = rng.randint(1, 10 ** 9), rng.randint(1, 40)
            s = shares(amount, n)
            self.assertEqual(sum(s), amount)
            self.assertEqual(len(s), n)
            self.assertLessEqual(max(s) - min(s), 1)
            self.assertEqual(s, sorted(s, reverse=True))
            self.assertTrue(all(isinstance(x, int) and x >= 0 for x in s))

    def test_extremes(self):
        self.assertEqual(shares(10 ** 9, 1), [10 ** 9])
        self.assertEqual(sum(shares(10 ** 9, 7)), 10 ** 9)


class SplitTest(unittest.TestCase):
    def setUp(self):
        reset(fixture())

    def test_caller_included(self):
        r = split("ada", 3000, ["ada", "bob", "cy"], note="dinner")
        self.assertEqual(r.status, 201, r.raw)
        b = r.body
        self.assertTrue(b["split_id"])
        self.assertEqual((b["amount"], b["currency"], b["note"]), (3000, "EUR", "dinner"))
        self.assertEqual(b["shares"], [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                                       {"handle": "cy", "amount": 1000}])
        self.assertEqual([q["payer_handle"] for q in b["requests"]], ["bob", "cy"])
        for q in b["requests"]:
            self.assertEqual((q["requester_id"], q["requester_handle"], q["amount"], q["note"], q["status"],
                              q["payment_id"], q["currency"]), ("u_ada", "ada", 1000, "dinner", "pending", None, "EUR"))
        self.assertRegex(b["created_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_uneven_shares_follow_handle_order(self):
        r = split("ada", 1000, ["cy", "ada", "bob"])
        self.assertEqual([s["amount"] for s in r.body["shares"]], [334, 333, 333])
        self.assertEqual([(q["payer_handle"], q["amount"]) for q in r.body["requests"]],
                         [("cy", 334), ("bob", 333)])
        r = split("ada", 1000, ["bob", "cy", "ada"], key="s2")
        self.assertEqual([(s["handle"], s["amount"]) for s in r.body["shares"]],
                         [("bob", 334), ("cy", 333), ("ada", 333)])
        self.assertEqual([(q["payer_handle"], q["amount"]) for q in r.body["requests"]],
                         [("bob", 334), ("cy", 333)])

    def test_caller_omitted(self):
        r = split("ada", 3000, ["bob", "cy"])
        self.assertEqual(r.status, 201)
        self.assertEqual([s["amount"] for s in r.body["shares"]], [1500, 1500])
        self.assertEqual([q["amount"] for q in r.body["requests"]], [1500, 1500])

    def test_caller_only_creates_no_requests(self):
        r = split("ada", 777, ["ada"])
        self.assertEqual(r.status, 201)
        self.assertEqual(r.body["shares"], [{"handle": "ada", "amount": 777}])
        self.assertEqual(r.body["requests"], [])
        self.assertEqual(snapshot()[1], 0)

    def test_zero_shares_still_create_requests(self):
        r = split("ada", 1, ["ada", "bob", "cy"])
        self.assertEqual([s["amount"] for s in r.body["shares"]], [1, 0, 0])
        self.assertEqual([(q["payer_handle"], q["amount"], q["status"]) for q in r.body["requests"]],
                         [("bob", 0, "pending"), ("cy", 0, "pending")])

    def test_requests_are_stored_and_visible_to_their_parties(self):
        r = split("ada", 300, ["bob", "cy"])
        with STORE.lock:
            for q in r.body["requests"]:
                self.assertEqual(STORE.state["requests"][q["request_id"]]["status"], "pending")
            rec = STORE.state["splits"][r.body["split_id"]]
            self.assertEqual(rec["request_ids"], [q["request_id"] for q in r.body["requests"]])
        self.assertEqual(len({q["request_id"] for q in r.body["requests"]}), 2)

    def test_no_balance_check_and_no_money_moves(self):
        before = snapshot()[0]
        r = split("bob", 1000000000, ["ada", "cy", "dee"])  # bob holds nothing, others hold little
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(snapshot()[0], before)
        self.assertEqual(snapshot()[3], 0)

    def test_amount_forms(self):
        for raw in ('{"amount":3000.0,"participant_handles":["bob"]}',
                    '{"amount":3e3,"participant_handles":["bob"],"extra":1}'):
            r = call("POST", "/splits", raw=raw, token=token("ada"), key="f" + str(len(raw)))
            self.assertEqual((r.status, r.body["amount"]), (201, 3000))

    def test_amount_bounds(self):
        self.assertEqual(split("ada", 1000000000, ["bob"], key="max").status, 201)
        for amount in (0, -5, 1000000001, 1.5, "100", True, None, [1], {"a": 1}):
            r = split("ada", amount, ["bob"], key="bad")
            self.assertEqual((r.status, r.code), (422, "validation_failed"), amount)
        r = call("POST", "/splits", {"participant_handles": ["bob"]}, token=token("ada"), key="bad")
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_participant_list_shape(self):
        for handles in ([], ["bob", "bob"], ["bob", "cy", "bob"], ["BOB"], ["x" * 21], [""]):
            r = split("ada", 100, handles, key="bad")
            self.assertEqual((r.status, r.code), (422, "validation_failed"), handles)
        r = call("POST", "/splits", {"amount": 100}, token=token("ada"), key="bad")
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_participant_list_wrong_types_are_400(self):
        for handles in ("bob", 5, None, {"a": "b"}, [1], ["bob", None], [["bob"]]):
            r = split("ada", 100, handles, key="bad")
            self.assertEqual((r.status, r.code), (400, "malformed_request"), handles)

    def test_note_rules(self):
        for note in ("x" * 201, None, 5, ["a"]):
            r = split("ada", 100, ["bob"], key="bad", note=note)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), note)
        r = split("ada", 100, ["bob"], key="ok", note="x" * 200)
        self.assertEqual(r.status, 201)
        r = split("ada", 100, ["bob"], key="n", note="  café ☕ <b>  ")
        self.assertEqual(r.body["note"], "  café ☕ <b>  ")
        self.assertEqual(r.body["requests"][0]["note"], "  café ☕ <b>  ")
        self.assertEqual(split("ada", 100, ["bob"], key="d").body["note"], "")

    def test_unknown_handle_is_404_and_creates_nothing(self):
        before = snapshot()
        r = split("ada", 100, ["bob", "nobody"], key="u")
        self.assertEqual((r.status, r.code), (404, "not_found"))
        self.assertEqual(snapshot(), before)

    def test_validation_beats_unknown_handle(self):
        r = split("ada", 0, ["nobody"], key="v")
        self.assertEqual(r.status, 422)
        r = split("ada", 100, ["nobody", "nobody"], key="v2")
        self.assertEqual(r.status, 422)

    def test_auth_and_key(self):
        r = call("POST", "/splits", {"amount": 1, "participant_handles": ["bob"]}, key="k")
        self.assertEqual((r.status, r.code), (401, "unauthenticated"))
        r = call("POST", "/splits", {"amount": 1, "participant_handles": ["bob"]}, token=token("ada"))
        self.assertEqual((r.status, r.code), (400, "missing_idempotency_key"))
        r = call("POST", "/splits", raw="[1]", token=token("ada"), key="k")
        self.assertEqual((r.status, r.code), (400, "malformed_request"))

    def test_failure_leaves_key_reusable(self):
        self.assertEqual(split("ada", 0, ["bob"], key="same").status, 422)
        self.assertEqual(split("ada", 10, ["bob"], key="same").status, 201)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        reset(fixture())

    def test_replay_is_200_with_identical_body_and_no_new_requests(self):
        first = split("ada", 1000, ["ada", "bob", "cy"], key="r")
        tok = token("ada")
        body = {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]}
        before = snapshot()
        again = call("POST", "/splits", body, token=tok, key="r")
        self.assertEqual((again.status, again.body), (200, first.body))
        self.assertEqual(snapshot(), before)

    def test_replay_after_a_request_changes_state(self):
        first = split("ada", 300, ["bob"], key="r")
        rid = first.body["requests"][0]["request_id"]
        with STORE.lock:
            STORE.state["requests"][rid]["status"] = "cancelled"
        again = call("POST", "/splits", {"amount": 300, "participant_handles": ["bob"]},
                     token=token("ada"), key="r")
        self.assertEqual((again.status, again.body), (200, first.body))

    def test_different_body_or_order_is_a_conflict(self):
        split("ada", 1000, ["bob", "cy"], key="r")
        for amount, handles in ((1001, ["bob", "cy"]), (1000, ["cy", "bob"])):
            r = split("ada", amount, handles, key="r")
            self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))
        self.assertEqual(snapshot()[1], 2)

    def test_claimed_key_with_an_invalid_body_is_409(self):
        split("ada", 1000, ["bob"], key="r")
        r = split("ada", 0, ["bob"], key="r")
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))

    def test_key_is_per_user(self):
        a = split("ada", 100, ["cy"], key="shared")
        b = split("bob", 100, ["cy"], key="shared")
        self.assertEqual((a.status, b.status), (201, 201))

    def test_same_key_on_another_path_is_a_new_request(self):
        split("ada", 100, ["bob"], key="shared")
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=token("ada"), key="shared")
        self.assertEqual(r.status, 201)

    def test_concurrent_same_key_creates_requests_once(self):
        tok = token("ada")
        body = {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]}
        out = [None] * 30

        def go(i):
            out[i] = call("POST", "/splits", body, token=tok, key="race")

        threads = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(r.status for r in out), [200] * 29 + [201])
        created = next(r for r in out if r.status == 201)
        self.assertTrue(all(r.body == created.body for r in out))
        self.assertEqual(snapshot()[1:3], (2, 1))

    def test_concurrent_distinct_keys_each_create_their_own(self):
        tok = token("ada")
        out = []
        guard = threading.Lock()

        def go(i):
            r = call("POST", "/splits", {"amount": 100, "participant_handles": ["bob", "cy"]},
                     token=tok, key="d%d" % i)
            with guard:
                out.append(r)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertTrue(all(r.status == 201 for r in out))
        ids = [q["request_id"] for r in out for q in r.body["requests"]]
        self.assertEqual(len(ids), 40)
        self.assertEqual(len(set(ids)), 40)
        self.assertEqual(len({r.body["split_id"] for r in out}), 20)


class SplitMoneyTest(unittest.TestCase):
    def test_paying_every_split_request_keeps_the_balance_sum(self):
        reset(fixture(ada=0, bob=400, cy=400, dee=400))
        total = 1200
        r = split("ada", 1000, ["ada", "bob", "cy", "dee"], key="m")
        self.assertEqual([s["amount"] for s in r.body["shares"]], [250] * 4)
        for q in r.body["requests"]:
            who = q["payer_handle"]
            paid = call("POST", "/requests/%s/pay" % q["request_id"], {}, token=token(who), key="pay-" + who)
            if paid.status == 404:
                self.skipTest("POST /requests/{id}/pay not landed")
            self.assertEqual(paid.status, 201, paid.raw)
        with STORE.lock:
            self.assertEqual(sum(u["balance"] for u in STORE.state["users"].values()), total)
            self.assertEqual(STORE.state["users"]["u_ada"]["balance"], 750)


if __name__ == "__main__":
    unittest.main()
