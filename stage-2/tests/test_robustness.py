"""S1.11: no input may crash, wedge or 5xx the service (spec §5, §4 amounts, §2 timeouts)."""
import time
import unittest
import uuid

from harness import call, reset
from test_payments import balances, token


def alive(test):
    r = call("GET", "/health")
    test.assertEqual(r.status, 200)


class HugeNumberTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")

    def post(self, amount_literal, path="/payments", field="to_handle", target="bob"):
        started = time.monotonic()
        r = call("POST", path, token=self.ada, key=uuid.uuid4().hex,
                 raw='{"%s":"%s","amount":%s}' % (field, target, amount_literal))
        self.assertLess(time.monotonic() - started, 5)
        return r

    def test_5000_digit_integer_is_422(self):
        r = self.post("9" * 5000)
        self.assertEqual((r.status, r.code), (422, "validation_failed"), r.raw)
        r = self.post("-" + "9" * 5000)
        self.assertEqual((r.status, r.code), (422, "validation_failed"))

    def test_huge_and_tiny_exponents_are_422_and_do_not_wedge(self):
        for literal in ("1e999999999", "-1e999999999", "1e-999999999", "1E+999999999",
                        "123456789e999999999", "1.5e999999999", "0.0000001e1"):
            r = self.post(literal)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), literal)
            alive(self)
        r = self.post("1e999999999", path="/requests", field="payer_handle")
        self.assertEqual(r.status, 422)
        self.assertEqual(balances()["ada"], 10000)

    def test_long_exact_forms_of_valid_amount(self):
        r = self.post("1000." + "0" * 5000)
        self.assertEqual((r.status, r.body["amount"]), (201, 1000))
        r = self.post("0.0001e7")
        self.assertEqual((r.status, r.body["amount"]), (201, 1000))
        r = self.post("1000000000" + "." + "0" * 30 + "1")
        self.assertEqual(r.status, 422)

    def test_replay_canonical_with_huge_numbers_in_unknown_fields(self):
        k = uuid.uuid4().hex
        body = '{"to_handle":"bob","amount":1000,"x":1e999999999,"y":%s}' % ("7" * 5000)
        first = call("POST", "/payments", token=self.ada, key=k, raw=body)
        self.assertEqual(first.status, 201, first.raw)
        again = call("POST", "/payments", token=self.ada, key=k,
                     raw='{"y":%s,"x":10e999999998,"amount":1e3,"to_handle":"bob"}'
                     % ("7" * 5000))
        self.assertEqual((again.status, again.body), (200, first.body))
        other = call("POST", "/payments", token=self.ada, key=k,
                     raw='{"to_handle":"bob","amount":1000,"x":1e999999999,"y":%s8}'
                     % ("7" * 4999))
        self.assertEqual(other.code, "idempotency_key_reuse")

    def test_huge_fixture_numbers_are_422(self):
        for literal in ("1e999999999", "9" * 5000, "9007199254740993", "-1"):
            raw = ('{"currency":"EUR","minor_units":2,"users":[{"id":"u","email":"u@e.com",'
                   '"password":"password1","display_name":"U","handle":"u","balance":%s}]}'
                   % literal)
            r = call("POST", "/_test/reset", raw=raw)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), literal)
            alive(self)
        r = call("POST", "/_test/reset", raw='{"currency":"EUR","minor_units":2e0,"users":[]}')
        self.assertEqual(r.status, 204)

    def test_fixture_integral_decimals_stored_as_int(self):
        from app.store import STORE
        raw = ('{"currency":"EUR","minor_units":2.0,"users":[{"id":"u","email":"u@e.com",'
               '"password":"password1","display_name":"U","handle":"u","balance":1.5e3}]}')
        self.assertEqual(call("POST", "/_test/reset", raw=raw).status, 204)
        with STORE.lock:
            self.assertIs(type(STORE.state["users"]["u"]["balance"]), int)
            self.assertIs(type(STORE.state["minor_units"]), int)

    def test_huge_query_integers(self):
        r = call("GET", "/activity?offset=" + "9" * 5000, token=self.ada)
        self.assertEqual((r.status, r.body["payments"], r.body["has_more"]), (200, [], False))
        r = call("GET", "/activity?limit=" + "9" * 5000, token=self.ada)
        self.assertEqual((r.status, r.code), (422, "validation_failed"))
        r = call("GET", "/requests?limit=" + "0" * 50 + "7", token=self.ada)
        self.assertEqual(r.status, 200)


class DeepNestingTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")

    def test_1000_deep_unknown_field_is_accepted(self):
        raw = '{"to_handle":"bob","amount":1,"junk":%s0%s}' % ("[" * 1000, "]" * 1000)
        k = uuid.uuid4().hex
        r = call("POST", "/payments", token=self.ada, key=k, raw=raw)
        self.assertIn(r.status, (201, 400), r.raw)
        if r.status == 201:
            self.assertEqual(call("POST", "/payments", token=self.ada, key=k,
                                  raw=raw).status, 200)
        alive(self)

    def test_100000_deep_is_400_everywhere(self):
        deep = "[" * 100000 + "]" * 100000
        cases = [("/payments", '{"to_handle":"bob","amount":1,"x":%s}' % deep, self.ada),
                 ("/_test/reset", deep, None),
                 ("/auth/login", '{"email":%s}' % deep, None),
                 ("/auth/signup", "{" * 50000 + "}" * 50000, None)]
        for path, raw, tok in cases:
            r = call("POST", path, raw=raw, token=tok, key=uuid.uuid4().hex)
            self.assertEqual((r.status, r.code), (400, "malformed_request"), path)
            alive(self)


class TextEdgeTest(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")

    def test_lone_surrogate_anywhere_is_400_and_changes_nothing(self):
        for raw in ('{"to_handle":"bob","amount":1,"note":"a\\ud800b"}',
                    '{"to_handle":"bob","amount":1,"x":{"\\udfff":1}}',
                    '{"to_handle":"bob","amount":1,"note":"\\udc00\\ud800"}'):
            r = call("POST", "/payments", token=self.ada, key=uuid.uuid4().hex, raw=raw)
            self.assertEqual((r.status, r.code), (400, "malformed_request"), raw)
        r = call("POST", "/auth/signup", raw='{"email":"s@e.com","password":"password1",'
                                            '"display_name":"\\ud83d"}')
        self.assertEqual(r.status, 400)
        self.assertEqual(balances()["ada"], 10000)
        self.assertEqual(call("GET", "/activity", token=self.ada).status, 200)

    def test_valid_surrogate_pair_emoji_round_trips(self):
        r = call("POST", "/payments", token=self.ada, key=uuid.uuid4().hex,
                 raw='{"to_handle":"bob","amount":1,"note":"\\ud83c\\udf55"}')
        self.assertEqual((r.status, r.body["note"]), (201, "\U0001F355"))

    def test_trailing_newline_never_matches_a_format(self):
        for q in ("/activity?limit=4%0A", "/requests?offset=0%0A", "/activity?offset=%0A"):
            r = call("GET", q, token=self.ada)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), q)
        r = call("POST", "/auth/signup", {"email": "nl@example.org\n",
                                          "password": "password1", "display_name": "N"})
        self.assertEqual(r.status, 422)
        r = call("POST", "/payments", {"to_handle": "bob\n", "amount": 1}, token=self.ada,
                 key=uuid.uuid4().hex)
        self.assertEqual(r.status, 422)
        r = call("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": [
            {"id": "u", "email": "u@e.com", "password": "password1", "display_name": "U",
             "handle": "bob\n", "balance": 1}]})
        self.assertEqual(r.status, 422)

    def test_unknown_field_with_huge_number_is_ignored(self):
        r = call("POST", "/payments", token=self.ada, key=uuid.uuid4().hex,
                 raw='{"to_handle":"bob","amount":5,"extra":1e999999999}')
        self.assertEqual(r.status, 201, r.raw)

    def test_invalid_utf8_body_is_400(self):
        r = call("POST", "/payments", token=self.ada, key=uuid.uuid4().hex,
                 raw=b'{"to_handle":"b\xff"}')
        self.assertEqual((r.status, r.code), (400, "malformed_request"))


class PaymentShapeTest(unittest.TestCase):
    def test_exact_key_set(self):
        reset()
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                 token=token("ada@example.com"), key=uuid.uuid4().hex)
        self.assertEqual(set(r.body) - {"authorization_id"}, {
            "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
            "currency", "note", "visibility", "request_id", "settlement_id", "created_at"})
        self.assertIsNone(r.body["settlement_id"])
        self.assertIsNone(r.body["request_id"])


class LockScopeTest(unittest.TestCase):
    def test_reset_racing_writes_never_5xx(self):
        import threading
        reset()
        tokens = [token("ada@example.com") for _ in range(4)]
        stop = time.monotonic() + 2
        statuses = []

        def writer(tok):
            while time.monotonic() < stop:
                statuses.append(call("POST", "/payments", {"to_handle": "bob", "amount": 1},
                                     token=tok, key=uuid.uuid4().hex).status)

        def resetter():
            while time.monotonic() < stop:
                reset()

        threads = [threading.Thread(target=writer, args=(t,)) for t in tokens]
        threads.append(threading.Thread(target=resetter))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(statuses)
        self.assertTrue(all(s < 500 for s in statuses), sorted(set(statuses)))


if __name__ == "__main__":
    unittest.main()
