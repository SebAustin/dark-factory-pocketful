#!/usr/bin/env python3
"""Self-test of atomicity.py: a clean stand-in passes; each planted atomicity bug is caught.  python3 selftest_atomicity.py [bug ...]"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BUGS = ["partial_batch", "no_completeness", "batch_precedence", "key_on_failure", "batch_wrong_net", "batch_race", "batch_recorded",
        "no_stale", "no_overdraft", "refund_cap_off", "refund_from_total"]


def run(bug, port):
    srv = subprocess.Popen([PY, os.path.join(HERE, "fake_service.py")], env=dict(os.environ, PORT=str(port), BUG=bug), cwd=HERE)
    time.sleep(0.8)
    try:
        out = subprocess.run([PY, os.path.join(HERE, "atomicity.py"), "--seed", "4", "--concurrent", "4"], env=dict(os.environ, TARGET_URL=f"http://127.0.0.1:{port}"),
                             capture_output=True, text=True, timeout=600)
    finally:
        srv.terminate()
    return out.returncode, out.stdout + out.stderr


def main():
    wanted = sys.argv[1:] or ["clean"] + BUGS
    failed = 0
    for i, bug in enumerate(wanted):
        code, text = run("" if bug == "clean" else bug, 18370 + i)
        first = next((ln for ln in text.splitlines() if ln.startswith("DIVERGENCE")), "")
        if bug == "clean":
            ok = code == 0
            print(f"{'ok  ' if ok else 'FAIL'} clean stand-in passes" + ("" if ok else "\n" + text[-1500:]))
        else:
            ok = code == 1 and bool(first)
            print(f"{'ok  ' if ok else 'FAIL'} {bug:16s} caught: {first[:120] or '(not caught)'}")
        failed += not ok
    print("self-test:", "FAILED" if failed else "all planted atomicity bugs caught")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
