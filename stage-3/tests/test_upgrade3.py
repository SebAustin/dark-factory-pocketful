"""S3.5: populated stage-1 and stage-2 exports into stage 3, via the frozen code as subprocesses."""
import os
import socket
import subprocess
import sys
import time
import unittest

import upgrade_check3
from harness import port
from test_upgrade import free_port

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def start(folder):
    p = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=os.path.join(ROOT, folder),
                            env=dict(os.environ, PORT=str(p), PYTHONDONTWRITEBYTECODE="1"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", p), timeout=1):
                break
        except OSError:
            time.sleep(0.1)
    return proc, "http://127.0.0.1:%d" % p


@unittest.skipUnless(all(os.path.isdir(os.path.join(ROOT, s, "app"))
                         for s in ("stage-1", "stage-2")), "frozen stages not present")
class PopulatedUpgradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.procs = [start("stage-1"), start("stage-2")]

    @classmethod
    def tearDownClass(cls):
        for proc, _ in cls.procs:
            proc.terminate()
            proc.wait(timeout=10)

    def test_stage1_and_stage2_exports(self):
        upgrade_check3.failures.clear()
        target = "http://127.0.0.1:%d" % port()
        for stage, (_, src) in ((1, self.procs[0]), (2, self.procs[1])):
            upgrade_check3.check_target(target, upgrade_check3.drive(src, stage), stage)
        self.assertEqual(upgrade_check3.failures, [])


if __name__ == "__main__":
    unittest.main()
