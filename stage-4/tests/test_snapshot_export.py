"""S4.3: statement snapshots in stage-4 exports (L10), merged on import (L12, D-74)."""
import copy
import json
import unittest
import uuid

from harness import FIXTURE, call, reset
from test_payments import token
from test_statement import statement

from app.store import STORE


def key():
    return uuid.uuid4().hex


class Base(unittest.TestCase):
    def setUp(self):
        reset()
        self.ada = token("ada@example.com")
        call("POST", "/payments", {"to_handle": "bob", "amount": 10}, token=self.ada, key=key())

    def page(self, tok, snap, **kw):
        r = statement(tok, snapshot=snap, **kw)
        self.assertEqual(r.status, 200, r.raw)
        return r.body


class ExportTest(Base):
    def test_recipe_for_current_state_round_trips(self):
        snap = statement(self.ada).body["snapshot"]
        before = self.page(self.ada, snap)
        exported = call("GET", "/_test/export").body
        rec = exported["state"]["snapshots"]["tokens"][snap]
        self.assertEqual(set(rec), {"user", "start", "end", "known", "known_echo"})
        call("POST", "/payments", {"to_handle": "bob", "amount": 5}, token=self.ada, key=key())
        reset()
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        self.assertEqual(self.page(self.ada, snap), before)
        again = call("GET", "/_test/export").body
        self.assertEqual(again, exported)  # stage-4 round trip, snapshots included

    def test_destination_tokens_merge_and_reset_clears(self):
        exported = call("GET", "/_test/export").body  # no snapshots yet
        mine = statement(self.ada).body["snapshot"]
        before = self.page(self.ada, mine)
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        self.assertEqual(self.page(self.ada, mine), before)  # L12: kept across the import
        reset()
        self.assertEqual(statement(token("ada@example.com"), snapshot=mine).code, "not_found")

    def test_token_of_an_older_state_is_exported_frozen_and_deduplicated(self):
        first_export = call("GET", "/_test/export").body
        old = [statement(self.ada).body["snapshot"] for _ in range(3)]  # identical results
        before = self.page(self.ada, old[0])
        self.assertEqual(call("POST", "/_test/import", first_export).status, 204)
        call("POST", "/payments", {"to_handle": "bob", "amount": 7},
             token=token("ada@example.com"), key=key())
        exported = call("GET", "/_test/export").body
        snaps = exported["state"]["snapshots"]
        for t in old:
            self.assertIn("frozen", snaps["tokens"][t])
        self.assertEqual(len(snaps["frozen"]), 1)  # three tokens, one stored result
        reset()
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        self.assertEqual(self.page(self.ada, old[0]), before)
        self.assertEqual(self.page(self.ada, old[2], limit=1, offset=0)["entries"],
                         before["entries"][:1])

    def test_imported_token_wins_a_clash(self):
        snap = statement(self.ada).body["snapshot"]
        exported = call("GET", "/_test/export").body
        rec = exported["state"]["snapshots"]["tokens"][snap]
        with STORE.lock:  # same token string, different recipe in the destination
            STORE.snapshots[snap] = dict(STORE.snapshots[snap], known=STORE.snapshots[snap][
                "known"] - 3600)
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        with STORE.lock:
            self.assertEqual(str(STORE.snapshots[snap]["known"]), rec["known"])

    def test_invalid_snapshots_are_422_and_change_nothing(self):
        exported = call("GET", "/_test/export").body
        for bad in ("x", {"tokens": {"t": {"user": "u_nobody"}}, "frozen": {}},
                    {"tokens": {"t": {"user": "u_ada", "start": "x", "end": "1", "known": "1"}},
                     "frozen": {}},
                    {"tokens": {"t": {"user": "u_ada", "frozen": "nope"}}, "frozen": {}}):
            body = copy.deepcopy(exported)
            body["state"]["snapshots"] = bad
            r = call("POST", "/_test/import", body)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), bad)

    def test_export_size_stays_small_under_many_reads(self):
        for _ in range(300):
            statement(self.ada)
        size = len(json.dumps(call("GET", "/_test/export").body))
        self.assertLess(size, 300 * 400)  # ~ a recipe per token, no entries


if __name__ == "__main__":
    unittest.main()
