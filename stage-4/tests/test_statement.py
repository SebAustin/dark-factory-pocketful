"""S3.3: GET /statement and snapshots (stage 3; D-48, D-49, D-50, D-54)."""
import copy
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from harness import FIXTURE, call, reset
from test_payments import token

ENTRY_KEYS = ["payment", "delta", "revision", "effective_at", "recorded_at",
              "correction_batch_id", "balance_after"]


def iso(dt):
    return dt.isoformat(timespec="microseconds")


def statement(tok, **params):
    q = "&".join("{}={}".format(k, quote(str(v), safe="")) for k, v in params.items())
    return call("GET", "/statement" + ("?" + q if q else ""), token=tok)


class Base(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.t = [iso(now - timedelta(hours=h)) for h in (5, 4, 3, 2)]
        f = copy.deepcopy(FIXTURE)
        f["payments"] = [
            {"id": "p_9", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100,
             "created_at": self.t[0]},
            {"id": "p_10", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 40,
             "created_at": self.t[0]},                       # same instant: id order p_10 < p_9
            {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 300,
             "visibility": "private", "created_at": self.t[1]},
            {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 50,
             "created_at": self.t[2]}]                       # not ada's
        f["users"][0]["balance"] = 10000 - 100 + 40 - 300
        f["users"][1]["balance"] = 2500 + 100 - 40 - 50
        f["users"][2]["balance"] = 350
        reset(f)
        self.ada, self.bob, self.cy = (token(e + "@example.com") for e in ("ada", "bob", "cy"))

    def ok(self, tok, **params):
        r = statement(tok, **params)
        self.assertEqual(r.status, 200, r.raw)
        return r.body


class StatementTest(Base):
    def test_full_statement_shape_order_and_balances(self):
        s = self.ok(self.ada)
        self.assertEqual(list(s), ["opening_balance", "entries", "closing_balance", "has_more",
                                   "snapshot"])
        self.assertEqual(s["opening_balance"], 10000)
        ids = [e["payment"]["payment_id"] for e in s["entries"]]
        self.assertEqual(ids, ["p_10", "p_9", "p_2"])  # (effective_at, id code point)
        self.assertEqual([e["delta"] for e in s["entries"]], [40, -100, -300])
        self.assertEqual([e["balance_after"] for e in s["entries"]], [10040, 9940, 9640])
        self.assertEqual(s["closing_balance"], 9640)
        e = s["entries"][0]
        self.assertEqual(list(e), ENTRY_KEYS)
        self.assertEqual((e["revision"], e["effective_at"], e["recorded_at"]),
                         (1, self.t[0], self.t[0]))
        self.assertEqual(len(e["payment"]), 14)
        self.assertFalse(s["has_more"])
        self.assertTrue(isinstance(s["snapshot"], str) and s["snapshot"])

    def test_only_own_payments_even_public_ones(self):
        ids = [e["payment"]["payment_id"] for e in self.ok(self.cy)["entries"]]
        self.assertEqual(ids, ["p_2", "p_3"])

    def test_half_open_window(self):
        s = self.ok(self.ada, **{"from": self.t[0], "to": self.t[1]})
        self.assertEqual([e["payment"]["payment_id"] for e in s["entries"]], ["p_10", "p_9"])
        self.assertEqual((s["opening_balance"], s["closing_balance"]), (10000, 9940))
        s = self.ok(self.ada, **{"from": self.t[1]})
        self.assertEqual([e["payment"]["payment_id"] for e in s["entries"]], ["p_2"])
        self.assertEqual((s["opening_balance"], s["closing_balance"]), (9940, 9640))
        s = self.ok(self.ada, **{"from": self.t[1], "to": self.t[1]})  # from = to
        self.assertEqual((s["entries"], s["opening_balance"], s["closing_balance"]),
                         ([], 9940, 9940))

    def test_pagination_does_not_change_balances(self):
        whole = self.ok(self.ada)
        p1 = self.ok(self.ada, limit=2)
        p2 = self.ok(self.ada, limit=2, offset=2)
        self.assertEqual(p1["entries"] + p2["entries"], whole["entries"])
        self.assertTrue(p1["has_more"])
        self.assertFalse(p2["has_more"])
        for p in (p1, p2):
            self.assertEqual((p["opening_balance"], p["closing_balance"]), (10000, 9640))
        beyond = self.ok(self.ada, offset=10)
        self.assertEqual((beyond["entries"], beyond["has_more"]), ([], False))

    def test_api_payments_and_default_to(self):
        made = call("POST", "/payments", {"to_handle": "bob", "amount": 7}, token=self.ada,
                    key=uuid.uuid4().hex).body
        s = self.ok(self.ada)
        self.assertEqual(s["entries"][-1]["payment"]["payment_id"], made["payment_id"])
        self.assertEqual(s["closing_balance"], 9633)
        self.assertEqual(self.ok(self.ada, to=made["created_at"])["closing_balance"], 9640)

    def test_known_at_echo_and_selection(self):
        s = self.ok(self.ada, known_at=self.t[0])
        self.assertEqual(s["known_at"], self.t[0])
        self.assertEqual([e["payment"]["payment_id"] for e in s["entries"]], ["p_10", "p_9"])
        self.assertEqual(s["closing_balance"], 9940)

    def test_validation(self):
        for params in ({"from": "2026-09-24"}, {"to": ""}, {"known_at": "x"},
                       {"from": self.t[1], "to": self.t[0]}, {"limit": 0}, {"limit": 201},
                       {"offset": -1}):
            r = statement(self.ada, **params)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), params)
        self.assertEqual(statement(None).status, 401)


class SnapshotTest(Base):
    def test_snapshot_freezes_the_result(self):
        first = self.ok(self.ada, limit=1)
        token_ = first["snapshot"]
        call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=self.ada,
             key=uuid.uuid4().hex)
        page = self.ok(self.ada, snapshot=token_, limit=10)
        self.assertEqual(len(page["entries"]), 3)  # the later payment is not in it
        self.assertEqual((page["opening_balance"], page["closing_balance"], page["snapshot"]),
                         (10000, 9640, token_))
        self.assertEqual(page["entries"][0], first["entries"][0])
        self.assertEqual(self.ok(self.ada, snapshot=token_, offset=2, limit=1)["has_more"],
                         False)

    def test_snapshot_rules(self):
        token_ = self.ok(self.ada)["snapshot"]
        for extra in ({"from": self.t[0]}, {"to": self.t[0]}, {"known_at": self.t[0]},
                      {"from": ""}, {"limit": 0}):
            r = statement(self.ada, snapshot=token_, **extra)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), extra)
        self.assertEqual(statement(self.bob, snapshot=token_).code, "not_found")
        self.assertEqual(statement(self.ada, snapshot="nope").code, "not_found")
        self.assertEqual(statement(self.ada, snapshot=token_, unknown="x").status, 200)
        reset()
        ada = token("ada@example.com")
        self.assertEqual(statement(ada, snapshot=token_).code, "not_found")

    def test_tokens_survive_export_reset_import(self):  # stage 4: L10, L12, D-74
        token_ = self.ok(self.ada, limit=2)["snapshot"]
        before = self.ok(self.ada, snapshot=token_, limit=10)
        exported = call("GET", "/_test/export").body
        self.assertIn(token_, exported["state"]["snapshots"]["tokens"])
        exported_session = self.ada
        reset()
        fresh = token("ada@example.com")  # the reset ended the session too
        self.assertEqual(statement(fresh, snapshot=token_).code, "not_found")  # reset ends
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        # the export's session and snapshot both come back (stage-4 import replaces sessions)
        self.assertEqual(self.ok(exported_session, snapshot=token_, limit=10), before)

    def test_snapshot_reproduces_after_backdated_correction(self):
        first = self.ok(self.ada)
        r = call("POST", "/payments/p_2/corrections",
                 {"expected_revision": 1, "amount": 0, "effective_at": self.t[0],
                  "reason": "undo"}, token=self.ada, key=uuid.uuid4().hex)
        self.assertEqual(r.status, 201, r.raw)
        again = self.ok(self.ada, snapshot=first["snapshot"])
        self.assertEqual(again, first)
        fresh = self.ok(self.ada)
        self.assertNotEqual(fresh["entries"], first["entries"])

    def test_known_at_echo_kept_on_snapshot_pages(self):
        first = self.ok(self.ada, known_at=self.t[0])
        page = self.ok(self.ada, snapshot=first["snapshot"])
        self.assertEqual(page["known_at"], self.t[0])


if __name__ == "__main__":
    unittest.main()
