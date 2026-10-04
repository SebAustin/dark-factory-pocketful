"""Seven idempotent paths (new two), Accept negotiation, concurrency.

Ledger R2-HOLD.16, R2-SCR.5/6, R2-CONC.1, R2-HOLD.5/6.
"""
import json
import random
import threading

import pytest

from s2lib import assert_error, assert_me_identities, new_key, run_parallel


class Target:
    def __init__(self, w, api, kind):
        self.w, self.api, self.kind = w, api, kind
        if kind == "authorizations":
            self.token, self.path = w.tok["ada"], "/authorizations"
            self.body = {"to_handle": "bob", "amount": 100, "note": "n"}
            self.alt = {"to_handle": "bob", "amount": 101, "note": "n"}
            self.invalid = {"to_handle": "bob", "amount": -5}
        else:
            aid = api.authorize(w.tok["ada"], "bob", 1000).json()["authorization_id"]
            self.token, self.path = w.tok["bob"], f"/authorizations/{aid}/capture"
            self.body = {"amount": 100, "final": False}
            self.alt = {"amount": 101, "final": False}
            self.invalid = {"amount": 0}

    def send(self, key, body=None, token=None):
        return self.api.post(self.path, token or self.token, key,
                             self.body if body is None else body)


@pytest.fixture(params=["authorizations", "capture"])
def target(request, world, api):
    return Target(world, api, request.param)


def test_R2_HOLD_16_missing_or_empty_key_400(target, api):
    for key in (None, ""):
        assert_error(api.post(target.path, target.token, key, target.body), 400,
                     "missing_idempotency_key")


def test_R2_HOLD_16_key_length(target):
    assert_error(target.send("k" * 256), 422, "validation_failed")
    assert target.send("k" * 255).status_code == 201


def test_R2_HOLD_16_replay_200_identical(target):
    key = new_key()
    first = target.send(key)
    assert first.status_code == 201
    before = target.w.mes()
    again = target.send(key)
    assert again.status_code == 200 and again.json() == first.json()
    assert target.w.mes() == before


def test_R2_HOLD_16_reuse_409_and_claimed_before_validation(target):
    key = new_key()
    assert target.send(key).status_code == 201
    assert_error(target.send(key, target.alt), 409, "idempotency_key_reuse")
    assert_error(target.send(key, target.invalid), 409, "idempotency_key_reuse")


def test_R2_HOLD_16_failed_4xx_key_reusable(target):
    key = new_key()
    assert target.send(key, target.invalid).status_code == 422
    assert target.send(key).status_code == 201


def test_R2_HOLD_16_key_order_whitespace(target, api):
    key = new_key()
    assert target.send(key).status_code == 201
    raw = json.dumps(dict(reversed(list(target.body.items()))), indent=3).encode()
    assert api.call("POST", target.path, target.token, key, content=raw).status_code == 200


def test_R2_HOLD_16_per_user_scope(target, api):
    key = "shared-1"
    assert target.send(key).status_code == 201
    w = target.w
    if target.kind == "authorizations":
        r = api.post("/authorizations", w.tok["dee"], key, target.body)
    else:
        aid = api.authorize(w.tok["dee"], "cy", 500).json()["authorization_id"]
        r = api.post(f"/authorizations/{aid}/capture", w.tok["cy"], key, target.body)
    assert r.status_code == 201, r.text


def test_R2_HOLD_16_concurrent_identical_one_201(target):
    key = new_key()
    res = run_parallel(lambda _: target.send(key), 20)
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and codes.count(200) == 19, codes
    assert len({json.dumps(r.json(), sort_keys=True) for r in res}) == 1
    held = target.w.me("ada")["held"]
    assert held == (100 if target.kind == "authorizations" else 900)


def test_R2_HOLD_16_same_key_other_path(world, api):
    key = new_key()
    a1 = api.authorize(world.tok["ada"], "bob", 100).json()["authorization_id"]
    a2 = api.authorize(world.tok["ada"], "bob", 100).json()["authorization_id"]
    assert api.capture(world.tok["bob"], a1, {}, key=key).status_code == 201
    assert api.capture(world.tok["bob"], a2, {}, key=key).status_code == 201


# ---------------------------------------------------------------- negotiation (D-21)

@pytest.mark.parametrize("path", ["/requests", "/authorizations"])
def test_R2_SCR_5_SCR_6_html_vs_json(world, api, path):
    t = world.tok["ada"]
    html = api.get(path, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    assert html.status_code == 200
    assert html.headers["content-type"].lower().startswith("text/html")
    for accept in (None, "*/*", "application/json"):
        h = {} if accept is None else {"Accept": accept}
        r = api.get(path, t, headers=h)
        assert r.status_code == 200, (accept, r.text[:200])
        assert r.headers["content-type"].lower().startswith("application/json")
        assert isinstance(r.json(), dict)
        r = api.get(path, headers=h)
        assert_error(r, 401, "unauthenticated")


@pytest.mark.parametrize("path", ["/", "/split", "/signup", "/login", "/requests",
                                  "/authorizations"])
def test_R2_SCR_2_routes_serve_html(api, path):
    r = api.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.headers["content-type"].lower().startswith("text/html")


# ---------------------------------------------------------------- concurrency

def test_R2_CONC_1_capture_vs_void_race_single_outcome(world, api):
    for _ in range(8):
        aid = api.authorize(world.tok["ada"], "bob", 100).json()["authorization_id"]

        def act(i):
            if i % 2:
                return api.capture(world.tok["bob"], aid).status_code
            return api.void(world.tok["ada"], aid).status_code

        codes = run_parallel(act, 6)
        assert all(c in (200, 201, 409) for c in codes), codes
        st = next(a for a in api.auths(world.tok["ada"], limit=200)["authorizations"]
                  if a["authorization_id"] == aid)["status"]
        assert st in ("captured", "voided")
    world.assert_invariants()


def test_R2_CONC_1_HOLD_6_authorize_vs_payment_available_never_negative(world, api):
    tk = world.tok
    stop = threading.Event()
    bad = []

    def reader():
        while not stop.is_set():
            r = api.get("/me", tk["bob"])
            if r.status_code == 200:
                m = r.json()
                if m["available"] < 0 or m["available"] != m["total"] - m["held"]:
                    bad.append(m)

    th = threading.Thread(target=reader)
    th.start()

    def work(i):
        if i % 2:
            return api.authorize(tk["bob"], "ada", 400).status_code
        return api.pay(tk["bob"], "cy", 400).status_code

    codes = run_parallel(work, 30, workers=30)
    stop.set()
    th.join()
    assert not bad, bad[:3]
    assert codes.count(201) == 6, codes  # 2500 // 400 operations fit, whatever the mix
    world.assert_invariants()


def test_R2_CONC_1_HOLD_5_totals_conserved_mixed_concurrent(world, api):
    tk = world.tok
    rnd = random.Random(11)
    aids = [api.authorize(tk["ada"], "bob", 300).json()["authorization_id"] for _ in range(6)]

    def work(i):
        k = rnd.randint(0, 5)
        if k == 0:
            return api.pay(tk["ada"], "dee", rnd.randint(1, 500)).status_code
        if k == 1:
            return api.capture(tk["bob"], aids[i % 6], {"amount": 100, "final": False}
                               ).status_code
        if k == 2:
            return api.void(tk["ada"], aids[(i + 3) % 6]).status_code
        if k == 3:
            return api.authorize(tk["dee"], "cy", rnd.randint(1, 900)).status_code
        if k == 4:
            return api.post("/settlements", tk["op"], new_key(), {"transfers": [
                {"from_handle": "dee", "to_handle": "ada", "amount": 50},
                {"from_handle": "ada", "to_handle": "cy", "amount": 50}]}).status_code
        return api.get("/me", tk["ada"]).status_code

    codes = run_parallel(work, 150, workers=40)
    assert all(c < 500 for c in codes), codes
    ms = world.assert_invariants()
    for m in ms.values():
        assert_me_identities(m)
