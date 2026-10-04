"""§7 idempotency on all five write paths. Ledger R-7.x, R-5.4, R-5.16, R-8.25, R-8.32."""
import json

import pytest

from conftest import assert_error, base_fixture, new_key, run_parallel, user

PATHS = ["payments", "requests", "pay", "splits", "settlements"]


def op_world(make_world):
    fx = base_fixture(users=[
        user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 0),
        user("u_dee", "dee", 5000), user("u_op", "op", 0), user("u_op2", "op2", 0),
    ], settlement_operator_ids=["u_op", "u_op2"])
    return make_world(fx)


class Target:
    """Builds (token, path, body, alt_body) for one write path; alt_body differs."""

    def __init__(self, w, api, kind):
        self.w, self.api, self.kind = w, api, kind
        t = w.tok
        if kind == "payments":
            self.token, self.path = t["ada"], "/payments"
            self.body = {"to_handle": "bob", "amount": 100, "note": "n"}
            self.alt = {"to_handle": "bob", "amount": 101, "note": "n"}
            self.invalid = {"to_handle": "bob", "amount": -5}
        elif kind == "requests":
            self.token, self.path = t["bob"], "/requests"
            self.body = {"payer_handle": "ada", "amount": 100, "note": "n"}
            self.alt = {"payer_handle": "ada", "amount": 101, "note": "n"}
            self.invalid = {"payer_handle": "ada", "amount": -5}
        elif kind == "pay":
            rid = api.request(t["bob"], "ada", 100).json()["request_id"]
            self.rid = rid
            self.token, self.path = t["ada"], f"/requests/{rid}/pay"
            self.body = {"visibility": "private"}
            self.alt = {"visibility": "public"}
            self.invalid = {"visibility": "nope"}
        elif kind == "splits":
            self.token, self.path = t["ada"], "/splits"
            self.body = {"amount": 300, "participant_handles": ["ada", "bob", "cy"]}
            self.alt = {"amount": 301, "participant_handles": ["ada", "bob", "cy"]}
            self.invalid = {"amount": 0, "participant_handles": ["ada", "bob"]}
        elif kind == "settlements":
            self.token, self.path = t["op"], "/settlements"
            self.body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]}
            self.alt = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 101}]}
            self.invalid = {"transfers": []}

    def send(self, key, body=None, token=None):
        return self.api.post(self.path, token or self.token, key,
                             self.body if body is None else body)


@pytest.fixture(params=PATHS)
def target(request, make_world, api):
    w = op_world(make_world)
    return Target(w, api, request.param)


def test_R7_6_first_use_201(target):
    assert target.send(new_key()).status_code == 201


def test_R5_4_R7_5_missing_or_empty_key_400(target, api):
    for key in (None, ""):
        r = api.post(target.path, target.token, key, target.body)
        assert_error(r, 400, "missing_idempotency_key")
    target.w.assert_invariants()


def test_R5_16_key_length_255_ok_256_422(target):
    assert_error(target.send("k" * 256), 422, "validation_failed")
    assert target.send("k" * 255).status_code == 201


def test_R7_3_R7_7_replay_200_identical_body(target):
    key = new_key()
    first = target.send(key)
    assert first.status_code == 201
    before = target.w.balances()
    second = target.send(key)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert target.w.balances() == before


def test_R7_8_same_key_different_body_409(target):
    key = new_key()
    assert target.send(key).status_code == 201
    before = target.w.balances()
    assert_error(target.send(key, target.alt), 409, "idempotency_key_reuse")
    assert target.w.balances() == before


def test_R7_13_claimed_key_beats_validation(target):
    key = new_key()
    assert target.send(key).status_code == 201
    assert_error(target.send(key, target.invalid), 409, "idempotency_key_reuse")


def test_R7_2_same_key_two_users_independent(target, api):
    key = "shared-key-1"
    first = target.send(key)
    assert first.status_code == 201
    w = target.w
    if target.kind == "payments":
        r = api.post("/payments", w.tok["dee"], key, target.body)
    elif target.kind == "requests":
        r = api.post("/requests", w.tok["dee"], key, target.body)
    elif target.kind == "splits":
        r = api.post("/splits", w.tok["dee"], key,
                     {"amount": 300, "participant_handles": ["dee", "bob", "cy"]})
    elif target.kind == "pay":
        rid = api.request(w.tok["bob"], "dee", 100).json()["request_id"]
        r = api.post(f"/requests/{rid}/pay", w.tok["dee"], key, target.body)
    else:
        r = api.post("/settlements", w.tok["op2"], key, target.body)
    assert r.status_code == 201, r.text
    again = target.send(key)
    assert again.status_code == 200 and again.json() == first.json()


def test_R7_9_failed_4xx_key_reusable(target):
    key = new_key()
    assert target.send(key, target.invalid).status_code == 422
    r = target.send(key)
    assert r.status_code == 201, r.text
    assert target.send(key).status_code == 200


def test_R7_10_replay_key_order_whitespace_insensitive(target, api):
    key = new_key()
    assert target.send(key).status_code == 201
    reordered = dict(reversed(list(target.body.items())))
    raw = json.dumps(reordered, indent=4).encode()
    r = api.call("POST", target.path, target.token, key, content=raw)
    assert r.status_code == 200, r.text


def test_R7_11_concurrent_identical_one_201_rest_200(target):
    key = new_key()
    before = target.w.balances()
    results = run_parallel(lambda _: target.send(key), 20)
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1, codes
    assert codes.count(200) == 19, codes
    bodies = {json.dumps(r.json(), sort_keys=True) for r in results}
    assert len(bodies) == 1
    after = target.w.balances()
    assert sum(after.values()) == sum(before.values())
    if target.kind in ("payments", "pay", "settlements"):
        assert after["ada"] == before["ada"] - 100
        assert after["bob"] - before["bob"] == 100


# ---------- path-specific idempotency rows ----------

def test_R7_4_same_key_same_body_other_path_201(world, api):
    t = world.tok
    key = new_key()
    r1 = api.request(t["bob"], "ada", 100, key=key).json()["request_id"]
    r2 = api.request(t["bob"], "ada", 200).json()["request_id"]
    a = api.pay_request(t["ada"], r1, {}, key=key)
    b = api.pay_request(t["ada"], r2, {}, key=key)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)
    assert a.json()["payment_id"] != b.json()["payment_id"]
    assert api.balance(t["ada"]) == 10000 - 300


def test_R7_4_same_key_payments_vs_requests_paths(world, api):
    key = new_key()
    assert api.post("/payments", world.tok["ada"], key,
                    {"to_handle": "bob", "amount": 5}).status_code == 201
    assert api.post("/requests", world.tok["ada"], key,
                    {"payer_handle": "bob", "amount": 5}).status_code == 201


def test_R8_25_pay_empty_vs_explicit_public_409(world, api):
    rid = api.request(world.tok["bob"], "ada", 100).json()["request_id"]
    key = new_key()
    assert api.pay_request(world.tok["ada"], rid, {}, key=key).status_code == 201
    r = api.pay_request(world.tok["ada"], rid, {"visibility": "public"}, key=key)
    assert_error(r, 409, "idempotency_key_reuse")


def test_R8_32_pay_replay_after_paid_200_no_money(world, api):
    rid = api.request(world.tok["bob"], "ada", 100).json()["request_id"]
    key = new_key()
    first = api.pay_request(world.tok["ada"], rid, {}, key=key)
    assert first.status_code == 201
    again = api.pay_request(world.tok["ada"], rid, {}, key=key)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert api.balance(world.tok["ada"]) == 9900
    assert_error(api.pay_request(world.tok["ada"], rid, {}), 409, "request_not_pending")


def test_R7_12_replay_after_cancel_returns_original_pending(world, api):
    key = new_key()
    first = api.request(world.tok["bob"], "ada", 100, key=key)
    rid = first.json()["request_id"]
    assert api.post(f"/requests/{rid}/cancel", world.tok["bob"]).status_code == 200
    again = api.request(world.tok["bob"], "ada", 100, key=key)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert again.json()["status"] == "pending"
    # no second request was created
    assert len(api.requests_list(world.tok["bob"])["requests"]) == 1


def test_R7_12_replay_after_balance_drop_still_200(world, api):
    key = new_key()
    first = api.pay(world.tok["bob"], "ada", 2500, key=key)
    assert first.status_code == 201
    again = api.pay(world.tok["bob"], "ada", 2500, key=key)
    assert again.status_code == 200 and again.json() == first.json()
    assert api.balance(world.tok["bob"]) == 0


def test_R7_9_insufficient_then_funded_same_key_201(world, api):
    key = new_key()
    assert_error(api.pay(world.tok["cy"], "ada", 100, key=key), 409, "insufficient_funds")
    api.pay(world.tok["ada"], "cy", 100)
    assert api.pay(world.tok["cy"], "ada", 100, key=key).status_code == 201


def test_R7_9_not_found_then_different_body_same_key_201(world, api):
    key = new_key()
    assert_error(api.pay(world.tok["ada"], "nobody", 5, key=key), 404, "not_found")
    assert api.pay(world.tok["ada"], "bob", 7, key=key).status_code == 201


def test_R7_10_replay_1000_vs_1e3(world, api):
    key = new_key()
    a = api.call("POST", "/payments", world.tok["ada"], key,
                 content=b'{"to_handle":"bob","amount":1000}')
    assert a.status_code == 201
    b = api.call("POST", "/payments", world.tok["ada"], key,
                 content=b'{"to_handle":"bob","amount":1e3}')
    assert b.status_code != 409, b.text
    assert api.balance(world.tok["ada"]) == 9000
