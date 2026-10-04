"""S2.5: a real stage-1 export, produced by the frozen stage-1 code, imported into stage 2."""
import os
import socket
import subprocess
import sys
import time
import unittest

import upgrade_check
from harness import FIXTURE, call, port, reset

STAGE1_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "stage-1")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.path.isdir(os.path.join(STAGE1_DIR, "app")), "stage-1 not present")
class StageOneExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = dict(os.environ, PORT=str(cls.port), PYTHONDONTWRITEBYTECODE="1")
        cls.proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=STAGE1_DIR,
                                    env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
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

    def test_upgrade_rules(self):
        s1 = "http://127.0.0.1:%d" % self.port
        s2 = "http://127.0.0.1:%d" % port()
        upgrade_check.failures.clear()
        export, tokens, lost, receipt = upgrade_check.drive_stage1(s1)
        self.assertNotIn("authorizations", export["state"])  # it really is a stage-1 state
        upgrade_check.check_stage2(s2, export, tokens, lost, receipt)
        self.assertEqual(upgrade_check.failures, [])
        self.assertEqual(call("GET", "/health").status, 200)


@unittest.skipUnless(os.path.isdir(os.path.join(STAGE1_DIR, "app")), "stage-1 not present")
class SessionAcrossUpgradeTest(StageOneExportTest):
    """L5 (D-22): a stage-1 import keeps destination tokens of users it still contains."""

    def stage1_export(self):
        s1 = "http://127.0.0.1:%d" % self.port
        assert upgrade_check.call(s1, "POST", "/_test/reset", upgrade_check.FIXTURE)[0] == 204
        status, export = upgrade_check.call(s1, "GET", "/_test/export")
        assert status == 200 and "authorizations" not in export["state"]
        return export

    def dest_token(self, email):
        r = call("POST", "/auth/login", {"email": email, "password": "correct horse"})
        self.assertEqual(r.status, 200, r.raw)
        return r.body["token"]

    test_upgrade_rules = None  # inherited check runs once, in StageOneExportTest

    def test_destination_tokens_across_a_stage1_import(self):
        export = self.stage1_export()
        # destination: same u_ada; u_bob with a different email; u_cy with a different handle;
        # plus a user the export does not have.
        import copy
        f = copy.deepcopy(FIXTURE)
        f["users"][1]["email"] = "bob.other@example.com"
        f["users"][2]["handle"] = "cy_other"
        reset(f)
        ada = self.dest_token("ada@example.com")
        bob = self.dest_token("bob.other@example.com")
        cy = self.dest_token("cy@example.com")
        zed = call("POST", "/auth/signup", {"email": "zed@example.com",
                                            "password": "correct horse",
                                            "display_name": "Zed"}).body["token"]
        self.assertEqual(call("POST", "/_test/import", export).status, 204)
        self.assertEqual(call("GET", "/me", token=ada).status, 200)          # (1) same user
        self.assertEqual(call("GET", "/me", token=zed).status, 401)          # (2) absent
        self.assertEqual(call("GET", "/me", token=bob).status, 401)          # (3) other email
        self.assertEqual(call("GET", "/me", token=cy).status, 401)           # (3) other handle
        for tok in export["state"]["tokens"]:                                # (5) exported
            self.assertEqual(call("GET", "/me", token=tok).status, 200)
        me = call("GET", "/me", token=ada).body
        self.assertEqual((me["user_id"], me["total"]), ("u_ada", 10000 - 0))

    def test_stage2_import_stays_pure_replacement(self):
        reset()
        exported = call("GET", "/_test/export").body
        later = self.dest_token("ada@example.com")                  # not in the export
        self.assertEqual(call("POST", "/_test/import", exported).status, 204)
        self.assertEqual(call("GET", "/me", token=later).status, 401)        # (4)
        for tok in exported["state"]["tokens"]:
            self.assertEqual(call("GET", "/me", token=tok).status, 200)


if __name__ == "__main__":
    unittest.main()
