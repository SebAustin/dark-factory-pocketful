"""S4.4: populated stage-1/2/3 exports into stage 4, via the frozen code as subprocesses."""
import os
import unittest

import upgrade_check3
import upgrade_check4
from harness import port
from test_upgrade3 import ROOT, start


@unittest.skipUnless(all(os.path.isdir(os.path.join(ROOT, s, "app"))
                         for s in ("stage-1", "stage-2", "stage-3")), "frozen stages not present")
class PopulatedUpgrade4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.procs = [start("stage-1"), start("stage-2"), start("stage-3")]

    @classmethod
    def tearDownClass(cls):
        for proc, _ in cls.procs:
            proc.terminate()
            proc.wait(timeout=10)

    def test_stage1_2_3_exports(self):
        upgrade_check3.failures.clear()
        target = "http://127.0.0.1:%d" % port()
        for stage, (_, src) in zip((1, 2, 3), self.procs):
            run = upgrade_check4.drive_stage3(src) if stage == 3 \
                else upgrade_check3.drive(src, stage)
            upgrade_check4.check_stage4(target, run, stage)
        self.assertEqual(upgrade_check3.failures, [])


if __name__ == "__main__":
    unittest.main()
