#!/usr/bin/env python3
"""Self-test of the differential tool: a clean stand-in must pass, every planted bug must be caught.

    python3 selftest_diff.py [bug ...]     # default: all
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
BUGS = ["asof_exclusive", "ignore_known_at", "stmt_closed_to", "order_created", "page_balance", "snapshot_live", "avail_ignores",
        "hold_boundary", "no_stale", "no_overdraft", "replay_latest", "zero_hidden", "no_echo", "opening_moves"]


def run(bug, port, ops=70, conc=3):
    env = dict(os.environ, PORT=str(port), BUG=bug)
    srv = subprocess.Popen([PY, os.path.join(HERE, "fake_service.py")], env=env, cwd=HERE)
    time.sleep(0.8)
    try:
        out = subprocess.run([PY, os.path.join(HERE, "diff_run.py"), "--ops", str(ops), "--seed", "7", "--concurrent", str(conc), "--skip", "settlement,request", "--no-protocol"],
                             env=dict(os.environ, TARGET_URL=f"http://127.0.0.1:{port}"), capture_output=True, text=True, timeout=600)
    finally:
        srv.terminate()
    return out.returncode, out.stdout + out.stderr


def main():
    wanted = sys.argv[1:] or ["clean"] + BUGS
    failed = 0
    for i, bug in enumerate(wanted):
        code, text = run("" if bug == "clean" else bug, 18390 + i)
        first = next((ln for ln in text.splitlines() if ln.startswith("DIVERGENCE")), "")
        if bug == "clean":
            ok = code == 0
            print(f"{'ok  ' if ok else 'FAIL'} clean stand-in passes" + ("" if ok else "\n" + text[-1500:]))
        else:
            ok = code == 1 and bool(first)
            print(f"{'ok  ' if ok else 'FAIL'} {bug:16s} caught: {first[:110] or '(not caught)'}")
        failed += not ok
    print("self-test:", "FAILED" if failed else "all planted divergences caught")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
