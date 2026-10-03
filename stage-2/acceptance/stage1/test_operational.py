"""§2 delivery and §3.1/3.2 start-up. Ledger R-2.1, R-2.3, R-2.4, R-2.7, R-3.1, R-3.3.

File checks always run. Container checks run when ACCEPTANCE_DOCKER=1 (they build and start
the image themselves on ports 18190-18199, container prefix "analyst-ops").
"""
import os
import pathlib
import subprocess
import time
import uuid

import httpx
import pytest

STAGE = pathlib.Path(__file__).resolve().parent.parent.parent
DOCKER = os.environ.get("ACCEPTANCE_DOCKER") == "1"


def test_R2_1_dockerfile_and_runmd_exist():
    assert (STAGE / "Dockerfile").is_file()
    run = (STAGE / "RUN.md").read_text()
    assert "docker build" in run and "docker run" in run


def _wait_healthy(port, deadline_s=60.0):
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            if r.status_code == 200 and r.json() == {"status": "ok"}:
                return time.monotonic() - start
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.2)  # polling interval for readiness, not synchronisation of a result
    return None


@pytest.fixture(scope="module")
def image():
    if not DOCKER:
        pytest.skip("container checks need ACCEPTANCE_DOCKER=1")
    tag = "analyst-ops-s1"
    subprocess.run(["docker", "build", "-q", "-t", tag, str(STAGE)], check=True,
                   capture_output=True)
    return tag


def _run(image, args):
    name = f"analyst-ops-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--cpus", "2",
                    "--memory", "2g", *args, image], check=True, capture_output=True)
    return name


def test_R2_3_R2_7_R3_3_healthy_within_60s_on_port(image):
    name = _run(image, ["-e", "PORT=18191", "-p", "18191:18191"])
    try:
        elapsed = _wait_healthy(18191)
        assert elapsed is not None and elapsed < 60.0
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_R3_1_default_port_8080(image):
    name = _run(image, ["-p", "18192:8080"])
    try:
        assert _wait_healthy(18192) is not None
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_R2_4_no_outbound_network(image):
    net = f"analyst-ops-internal-{uuid.uuid4().hex[:6]}"
    subprocess.run(["docker", "network", "create", "--internal", net], check=True,
                   capture_output=True)
    name = _run(image, ["--network", net, "-e", "PORT=18193"])
    try:
        probe = ("import urllib.request,time\n"
                 "for _ in range(300):\n"
                 "  try:\n"
                 "    print(urllib.request.urlopen('http://127.0.0.1:18193/health').read());break\n"
                 "  except Exception: time.sleep(0.2)\n")
        out = subprocess.run(["docker", "exec", name, "python", "-c", probe],
                             capture_output=True, text=True, timeout=90)
        assert '"status"' in out.stdout and "ok" in out.stdout, out.stderr
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", net], capture_output=True)
