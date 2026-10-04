"""S3.1: a populated export from the frozen stage-2 code imports into stage 3 (plan §5)."""
import os
import subprocess
import sys
import time
import unittest

import upgrade_check
from harness import call
from test_upgrade import free_port

from app import instants
from app.store import STORE

STAGE2_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "stage-2")
PW = "correct horse"


@unittest.skipUnless(os.path.isdir(os.path.join(STAGE2_DIR, "app")), "stage-2 not present")
class StageTwoExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ, PORT=str(cls.port), PYTHONDONTWRITEBYTECODE="1")
        cls.proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=STAGE2_DIR,
                                    env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        import socket
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                    break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def drive(self):
        s2 = "http://127.0.0.1:%d" % self.port
        c = lambda *a, **k: upgrade_check.call(s2, *a, **k)
        fixture = dict(upgrade_check.FIXTURE, authorization_ttl_seconds=2)
        assert c("POST", "/_test/reset", fixture)[0] == 204
        ada = c("POST", "/auth/login", {"email": "ada@example.com", "password": PW})[1]["token"]
        bob = c("POST", "/auth/login", {"email": "bob@example.com", "password": PW})[1]["token"]
        holds = {}
        for name, amount in (("open", 100), ("partial", 200), ("final", 300), ("void", 400),
                             ("expire", 50)):
            holds[name] = c("POST", "/authorizations", {"to_handle": "bob", "amount": amount},
                            ada, "auth-" + name)[1]["authorization_id"]
        c("POST", "/authorizations/%s/capture" % holds["partial"], {"amount": 50,
                                                                     "final": False}, bob, "c1")
        c("POST", "/authorizations/%s/capture" % holds["final"], {"amount": 120}, bob, "c2")
        c("POST", "/authorizations/%s/void" % holds["void"], {}, ada)
        c("POST", "/payments", {"to_handle": "bob", "amount": 7}, ada, "pay-1")
        time.sleep(2.2)  # "expire" (and the still-open ones) pass their 2 s deadline
        holds["late"] = c("POST", "/authorizations", {"to_handle": "bob", "amount": 25}, ada,
                          "auth-late")[1]["authorization_id"]
        status, export = c("GET", "/_test/export")
        assert status == 200 and "revisions" not in str(export["state"]["payments"])
        return export, ada, holds

    def test_populated_stage2_export(self):
        export, ada, holds = self.drive()
        self.assertEqual(call("POST", "/_test/import", export).status, 204)
        with STORE.lock:
            state = STORE.state
            for p in state["payments"].values():
                self.assertEqual(p["revisions"][0]["amount"], p["amount"])
                self.assertEqual(p["revisions"][0]["effective_at"], p["created_at"])
            a = state["authorizations"]
            kinds = lambda aid: [(e["kind"], e["held_delta"]) for e in a[aid]["events"]]
            self.assertEqual(kinds(holds["partial"])[:2], [("created", 200), ("capture", -50)])
            self.assertEqual(kinds(holds["final"]),
                             [("created", 300), ("capture", -120), ("release", -180)])
            self.assertEqual(a[holds["final"]]["closed_at"],
                             a[holds["final"]]["events"][1]["at"])
            self.assertEqual(kinds(holds["void"]), [("created", 400), ("release", -400)])
            self.assertEqual(a[holds["expire"]]["status"], "expired")
            self.assertEqual(a[holds["expire"]]["closed_at"], a[holds["expire"]]["expires_at"])
            self.assertEqual(a[holds["late"]]["status"], "open")
            self.assertIsNone(a[holds["late"]]["closed_at"])
            ada_user = state["users"]["u_ada"]
            self.assertEqual(ada_user["held"], 25)
            self.assertEqual(ada_user["opening"], 10500)  # seeded 10000 after paying 500
        me = call("GET", "/me", token=ada).body
        self.assertEqual((me["held"], me["available"]), (25, me["total"] - 25))
        r = call("POST", "/payments", {"to_handle": "bob", "amount": 7}, token=ada, key="pay-1")
        self.assertEqual(r.status, 200)  # stage 2 receipt replays unchanged
        first = call("GET", "/_test/export").body
        self.assertEqual(call("POST", "/_test/import", first).status, 204)
        self.assertEqual(call("GET", "/_test/export").body, first)
        made = call("POST", "/payments", {"to_handle": "bob", "amount": 1}, token=ada,
                    key="after").body
        self.assertGreater(instants.key(made["created_at"]),
                           max(instants.key(p["created_at"])
                               for p in first["state"]["payments"].values()))


if __name__ == "__main__":
    unittest.main()
