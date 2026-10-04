import importlib.util
import threading
import unittest

from harness import call, reset

from app.store import STORE, new_token

HAS_IDEMPOTENCY = importlib.util.find_spec("app.idempotency") is not None
needs_idempotency = unittest.skipUnless(HAS_IDEMPOTENCY, "idempotency pipeline (S1.3) not landed")


def user(handle, balance):
    return {"id": "u_" + handle, "email": handle + "@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance}


def fixture(operators=("op",), **balances):
    base = {"op": 0, "ada": 100, "bob": 0, "cy": 0, "dee": 0}
    base.update(balances)
    return {"currency": "EUR", "minor_units": 2, "users": [user(h, b) for h, b in base.items()],
            "payments": [], "requests": [],
            "settlement_operator_ids": ["u_" + h for h in operators]}


def token(handle):
    with STORE.lock:
        return new_token(STORE.state, "u_" + handle)


def balances():
    with STORE.lock:
        return {u["handle"]: u["balance"] for u in STORE.state["users"].values()}


def payment_count():
    with STORE.lock:
        return len(STORE.state["payments"])


def tr(src, dst, amount, **extra):
    return {"from_handle": src, "to_handle": dst, "amount": amount, **extra}


def settle(who, transfers, key="k1", **kw):
    return call("POST", "/settlements", {"transfers": transfers}, token=token(who) if who else None,
                key=key, **kw)


class SettlementBase(unittest.TestCase):
    def setUp(self):
        reset(fixture())

    def assertUnchanged(self, before_balances, before_payments):
        self.assertEqual(balances(), before_balances)
        self.assertEqual(payment_count(), before_payments)


class AccessTest(SettlementBase):
    def test_no_token_is_401(self):
        r = settle(None, [tr("ada", "bob", 10)])
        self.assertEqual((r.status, r.code), (401, "unauthenticated"))

    def test_unknown_token_is_401(self):
        r = call("POST", "/settlements", {"transfers": [tr("ada", "bob", 10)]}, token="nope", key="k")
        self.assertEqual((r.status, r.code), (401, "unauthenticated"))

    def test_non_operator_is_403(self):
        r = settle("ada", [tr("ada", "bob", 10)])
        self.assertEqual((r.status, r.code), (403, "forbidden"))
        self.assertEqual(balances()["ada"], 100)

    def test_default_fixture_has_no_operators(self):
        f = fixture()
        del f["settlement_operator_ids"]
        reset(f)
        r = settle("op", [tr("ada", "bob", 10)])
        self.assertEqual(r.status, 403)

    def test_missing_key_is_400(self):
        r = call("POST", "/settlements", {"transfers": [tr("ada", "bob", 10)]}, token=token("op"))
        self.assertEqual((r.status, r.code), (400, "missing_idempotency_key"))

    def test_non_object_body_is_400(self):
        r = call("POST", "/settlements", raw="[1]", token=token("op"), key="k")
        self.assertEqual((r.status, r.code), (400, "malformed_request"))
        r = call("POST", "/settlements", raw="{nope", token=token("op"), key="k")
        self.assertEqual((r.status, r.code), (400, "malformed_request"))

    def test_operator_does_not_gain_request_or_private_access(self):
        f = fixture(bob=1)  # stage 3: seeded history must be consistent (bob received 1)
        f["requests"] = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                          "amount": 5, "note": "", "status": "pending"}]
        f["payments"] = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                          "amount": 1, "note": "", "visibility": "private"}]
        reset(f)
        if importlib.util.find_spec("app.requests_") is None:
            self.skipTest("GET /requests not landed")
        r = call("GET", "/requests", token=token("op"))
        self.assertEqual(r.body["requests"], [])


class SuccessTest(SettlementBase):
    def test_receipt_shape_and_balances(self):
        r = settle("op", [tr("ada", "bob", 60, note="rent"), tr("ada", "cy", 40, visibility="private")])
        self.assertEqual(r.status, 201, r.raw)
        body = r.body
        self.assertTrue(body["settlement_id"])
        self.assertEqual(len(body["payments"]), 2)
        first, second = body["payments"]
        self.assertEqual((first["from_handle"], first["to_handle"], first["amount"], first["note"],
                          first["visibility"]), ("ada", "bob", 60, "rent", "public"))
        self.assertEqual((second["to_handle"], second["note"], second["visibility"]),
                         ("cy", "", "private"))
        for p in body["payments"]:
            self.assertEqual(p["settlement_id"], body["settlement_id"])
            self.assertIsNone(p["request_id"])
            self.assertEqual(p["created_at"], body["committed_at"])
            self.assertEqual(p["currency"], "EUR")
        self.assertRegex(body["committed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$")
        self.assertEqual(balances(), {"op": 0, "ada": 0, "bob": 60, "cy": 40, "dee": 0})

    def test_chain_through_a_zero_wallet_is_affordable(self):
        # bob holds nothing but ends at 0 net: the settlement is affordable as a whole.
        r = settle("op", [tr("bob", "cy", 100), tr("ada", "bob", 100)])
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(balances(), {"op": 0, "ada": 0, "bob": 0, "cy": 100, "dee": 0})

    def test_cycle_among_empty_wallets_nets_to_zero(self):
        r = settle("op", [tr("bob", "cy", 5), tr("cy", "dee", 5), tr("dee", "bob", 5)])
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(balances()["bob"] + balances()["cy"] + balances()["dee"], 0)

    def test_operator_may_move_other_wallets_and_be_a_party(self):
        r = settle("op", [tr("ada", "op", 100), tr("op", "bob", 30)])
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual((balances()["op"], balances()["bob"]), (70, 30))

    def test_amount_forms_and_unknown_fields(self):
        t = [tr("ada", "bob", 1000.0 / 1000), tr("ada", "cy", 1e1, extra="ignored")]
        r = call("POST", "/settlements", raw='{"transfers":[{"from_handle":"ada","to_handle":"bob",'
                 '"amount":1.0},{"from_handle":"ada","to_handle":"cy","amount":1e1,"zzz":1}],"x":2}',
                 token=token("op"), key="k")
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual([p["amount"] for p in r.body["payments"]], [1, 10])
        del t

    def test_note_is_verbatim(self):
        note = "  café ☕ <b>&amp;</b>  "
        r = settle("op", [tr("ada", "bob", 1, note=note)])
        self.assertEqual(r.body["payments"][0]["note"], note)

    def test_exact_32_transfers(self):
        r = settle("op", [tr("ada", "bob", 1)] * 32)
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(len(r.body["payments"]), 32)
        self.assertEqual(balances()["bob"], 32)

    def test_members_are_ordinary_payments_in_the_feed(self):
        r = settle("op", [tr("ada", "bob", 10), tr("ada", "cy", 10, visibility="private")])
        if importlib.util.find_spec("app.payments") is None:
            self.skipTest("GET /activity not landed")
        public_id, private_id = (p["payment_id"] for p in r.body["payments"])
        ids = lambda who: [p["payment_id"] for p in call("GET", "/activity", token=token(who)).body["payments"]]  # noqa: E731
        self.assertIn(public_id, ids("dee"))
        self.assertNotIn(private_id, ids("dee"))
        self.assertIn(private_id, ids("cy"))
        self.assertIn(private_id, ids("ada"))
        self.assertNotIn(private_id, ids("op"))
        feed = call("GET", "/activity", token=token("dee")).body["payments"]
        member = next(p for p in feed if p["payment_id"] == public_id)
        self.assertEqual(member["settlement_id"], r.body["settlement_id"])

    def test_two_settlements_have_distinct_ids(self):
        a = settle("op", [tr("ada", "bob", 1)], key="a")
        b = settle("op", [tr("ada", "bob", 1)], key="b")
        self.assertNotEqual(a.body["settlement_id"], b.body["settlement_id"])
        self.assertNotEqual(a.body["payments"][0]["payment_id"], b.body["payments"][0]["payment_id"])


class FailureTest(SettlementBase):
    def assertFails(self, transfers, status, code):
        before = (balances(), payment_count())
        r = settle("op", transfers, key="fail-key")
        self.assertEqual((r.status, r.code), (status, code), r.raw)
        self.assertUnchanged(*before)

    def test_insufficient_collective_funds(self):
        self.assertFails([tr("ada", "bob", 101)], 409, "insufficient_funds")

    def test_one_underfunded_wallet_voids_the_whole_batch(self):
        self.assertFails([tr("ada", "bob", 50), tr("bob", "cy", 51)], 409, "insufficient_funds")

    def test_exactly_affordable_boundary(self):
        r = settle("op", [tr("ada", "bob", 100)])
        self.assertEqual(r.status, 201)
        self.assertEqual(balances()["ada"], 0)

    def test_bounds_of_transfers(self):
        self.assertFails([], 422, "validation_failed")
        self.assertFails([tr("ada", "bob", 1)] * 33, 422, "validation_failed")

    def test_transfers_shape(self):
        for body in ({}, {"transfers": None}, {"transfers": "x"}, {"transfers": {"a": 1}}):
            r = call("POST", "/settlements", body, token=token("op"), key="s")
            self.assertEqual((r.status, r.code), (422, "validation_failed"), body)
        self.assertEqual(payment_count(), 0)

    def test_entry_must_be_an_object(self):
        for entry in (1, "x", None, [], True):
            self.assertFails([entry], 422, "validation_failed")

    def test_missing_or_ill_typed_handles(self):
        self.assertFails([{"to_handle": "bob", "amount": 1}], 422, "validation_failed")
        self.assertFails([{"from_handle": "ada", "amount": 1}], 422, "validation_failed")
        self.assertFails([{"from_handle": 5, "to_handle": "bob", "amount": 1}], 422, "validation_failed")
        self.assertFails([tr("ADA", "bob", 1)], 422, "validation_failed")

    def test_amount_rules(self):
        for amount in (0, -1, 1000000001, 1.5, "10", True, None, [1]):
            self.assertFails([tr("ada", "bob", amount)], 422, "validation_failed")
        r = settle("op", [tr("ada", "bob", 1000000000)], key="big")
        self.assertEqual((r.status, r.code), (409, "insufficient_funds"))

    def test_note_rules(self):
        self.assertFails([tr("ada", "bob", 1, note=None)], 422, "validation_failed")
        self.assertFails([tr("ada", "bob", 1, note=5)], 422, "validation_failed")
        self.assertFails([tr("ada", "bob", 1, note="x" * 201)], 422, "validation_failed")
        r = settle("op", [tr("ada", "bob", 1, note="x" * 200)], key="ok")
        self.assertEqual(r.status, 201)

    def test_visibility_rules(self):
        for v in ("friends", "PUBLIC", None, 1):
            self.assertFails([tr("ada", "bob", 1, visibility=v)], 422, "validation_failed")

    def test_self_transfer(self):
        self.assertFails([tr("ada", "ada", 1)], 422, "self_payment")

    def test_unknown_handle(self):
        self.assertFails([tr("ada", "nobody", 1)], 404, "not_found")
        self.assertFails([tr("nobody", "bob", 1)], 404, "not_found")

    def test_entry_errors_precede_insufficient_funds(self):
        self.assertFails([tr("ada", "bob", 999), tr("ada", "nobody", 1)], 404, "not_found")
        self.assertFails([tr("ada", "bob", 999), tr("bob", "bob", 1)], 422, "self_payment")
        self.assertFails([tr("ada", "bob", 999), tr("ada", "bob", 0)], 422, "validation_failed")

    def test_first_erroneous_entry_in_input_order_wins(self):
        self.assertFails([tr("ada", "nobody", 1), tr("ada", "ada", 1)], 404, "not_found")
        self.assertFails([tr("ada", "ada", 1), tr("ada", "nobody", 1)], 422, "self_payment")
        self.assertFails([tr("ada", "nobody", 1), tr("ada", "bob", 0)], 404, "not_found")
        self.assertFails([tr("ada", "bob", 0), tr("ada", "nobody", 1)], 422, "validation_failed")

    def test_failure_claims_no_key(self):
        bad = settle("op", [tr("ada", "bob", 999)], key="same")
        self.assertEqual(bad.status, 409)
        good = settle("op", [tr("ada", "bob", 10)], key="same")
        self.assertEqual(good.status, 201, good.raw)

    def test_validation_failure_claims_no_key(self):
        self.assertEqual(settle("op", [], key="same").status, 422)
        self.assertEqual(settle("op", [tr("ada", "bob", 10)], key="same").status, 201)

    def test_operator_check_precedes_body_validation(self):
        r = settle("ada", [], key="k")
        self.assertEqual((r.status, r.code), (403, "forbidden"))


@needs_idempotency
class ReplayTest(SettlementBase):
    def test_replay_returns_200_with_original_body_and_moves_nothing(self):
        t = [tr("ada", "bob", 40), tr("ada", "cy", 10)]
        op = token("op")
        first = call("POST", "/settlements", {"transfers": t}, token=op, key="r1")
        self.assertEqual(first.status, 201)
        after = (balances(), payment_count())
        again = call("POST", "/settlements", {"transfers": t}, token=op, key="r1")
        self.assertEqual(again.status, 200)
        self.assertEqual(again.body, first.body)
        self.assertEqual((balances(), payment_count()), after)

    def test_replay_ignores_key_order_and_whitespace(self):
        op = token("op")
        raw1 = '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":10}]}'
        raw2 = '{ "transfers" : [ {"amount": 1e1, "to_handle":"bob", "from_handle":"ada"} ] }'
        first = call("POST", "/settlements", raw=raw1, token=op, key="r2")
        again = call("POST", "/settlements", raw=raw2, token=op, key="r2")
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(again.body, first.body)

    def test_same_key_different_body_is_409(self):
        op = token("op")
        call("POST", "/settlements", {"transfers": [tr("ada", "bob", 10)]}, token=op, key="r3")
        r = call("POST", "/settlements", {"transfers": [tr("ada", "bob", 11)]}, token=op, key="r3")
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))
        self.assertEqual(balances()["bob"], 10)

    def test_claimed_key_with_invalid_body_is_409_not_422(self):
        op = token("op")
        call("POST", "/settlements", {"transfers": [tr("ada", "bob", 10)]}, token=op, key="r4")
        r = call("POST", "/settlements", {"transfers": []}, token=op, key="r4")
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))

    def test_replay_survives_later_balance_changes(self):
        op = token("op")
        t = [tr("ada", "bob", 100)]
        first = call("POST", "/settlements", {"transfers": t}, token=op, key="r5")
        again = call("POST", "/settlements", {"transfers": t}, token=op, key="r5")  # ada now holds 0
        self.assertEqual((again.status, again.body), (200, first.body))

    def test_key_is_scoped_to_the_user(self):
        reset(fixture(operators=("op", "dee")))
        t = [tr("ada", "bob", 10)]
        a = call("POST", "/settlements", {"transfers": t}, token=token("op"), key="shared")
        b = call("POST", "/settlements", {"transfers": t}, token=token("dee"), key="shared")
        self.assertEqual((a.status, b.status), (201, 201))
        self.assertEqual(balances()["bob"], 20)

    def test_concurrent_same_key_applies_once(self):
        op = token("op")
        t = [tr("ada", "bob", 30), tr("ada", "cy", 30)]
        out = [None] * 20

        def go(i):
            out[i] = call("POST", "/settlements", {"transfers": t}, token=op, key="race")

        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        self.assertEqual(sorted(r.status for r in out), [200] * 19 + [201])
        self.assertTrue(all(r.body == out[0].body or r.status == 201 for r in out))
        created = next(r for r in out if r.status == 201)
        self.assertTrue(all(r.body == created.body for r in out))
        self.assertEqual(balances()["ada"], 40)
        self.assertEqual(payment_count(), 2)


class ConcurrencyTest(SettlementBase):
    def test_concurrent_distinct_batches_never_overdraw(self):
        out = []
        guard = threading.Lock()
        op = token("op")

        def go(i):
            r = call("POST", "/settlements", {"transfers": [tr("ada", "bob", 30), tr("bob", "cy", 10)]},
                     token=op, key="c%d" % i)
            with guard:
                out.append(r)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        wins = [r for r in out if r.status == 201]
        self.assertEqual(len(wins), 3)  # ada: 100 -> three batches of 30
        self.assertTrue(all(r.code == "insufficient_funds" for r in out if r.status != 201))
        b = balances()
        self.assertEqual(b, {"op": 0, "ada": 10, "bob": 60, "cy": 30, "dee": 0})
        self.assertEqual(sum(b.values()), 100)
        self.assertEqual(payment_count(), 6)

    def test_batch_members_are_all_or_none_in_state(self):
        r = settle("op", [tr("ada", "bob", 100), tr("bob", "cy", 100)])
        self.assertEqual(r.status, 201)
        with STORE.lock:
            rec = STORE.state["settlements"][r.body["settlement_id"]]
            self.assertEqual(rec["payment_ids"], [p["payment_id"] for p in r.body["payments"]])
            seqs = [STORE.state["payments"][i]["seq"] for i in rec["payment_ids"]]
            self.assertEqual(seqs, sorted(seqs))


if __name__ == "__main__":
    unittest.main()
