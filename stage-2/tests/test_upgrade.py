"""S2.5: a real stage-1 export, produced by the frozen stage-1 code, imported into stage 2."""
import os
import socket
import subprocess
import sys
import time
import unittest

import upgrade_check
from harness import call, port

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


if __name__ == "__main__":
    unittest.main()
