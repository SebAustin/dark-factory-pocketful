"""§10 export and import; §6 hashing evidence. Ledger R-10.x, R-11.21, R-6.11."""
import json
import time

import pytest

from conftest import (CONTROL_TIMEOUT, PASSWORD, assert_error, base_fixture, new_key, user)


def op_fixture():
    return base_fixture(users=[
        user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 0),
        user("u_dee", "dee", 5000), user("u_op", "op", 0),
    ], settlement_operator_ids=["u_op"])


def export(api):
    r = api.call("GET", "/_test/export", timeout=CONTROL_TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def do_import(api, obj, raw=None):
    if raw is not None:
        return api.call("POST", "/_test/import", content=raw, timeout=CONTROL_TIMEOUT)
    return api.call("POST", "/_test/import", json=obj, timeout=CONTROL_TIMEOUT)


def populate(api, w):
    """A state touching every record kind; returns receipts for replay checks."""
    tk = w.tok
    rec = {}
    rec["pay_key"] = new_key()
    rec["pay"] = api.pay(tk["ada"], "bob", 300, key=rec["pay_key"], note="café ☕",
                         visibility="private").json()
    rec["req_key"] = new_key()
    rec["req"] = api.request(tk["bob"], "ada", 700, key=rec["req_key"]).json()
    rec["payreq_key"] = new_key()
    rec["payreq"] = api.pay_request(tk["ada"], rec["req"]["request_id"], {},
                                    key=rec["payreq_key"]).json()
    rec["split_key"] = new_key()
    rec["split"] = api.post("/splits", tk["dee"], rec["split_key"],
                            {"amount": 1000, "participant_handles": ["dee", "ada", "cy"]}).json()
    rec["settle_key"] = new_key()
    rec["settle"] = api.post("/settlements", tk["op"], rec["settle_key"], {
        "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50},
                      {"from_handle": "cy", "to_handle": "dee", "amount": 50}]}).json()
    cancel = api.request(tk["cy"], "dee", 5).json()["request_id"]
    api.post(f"/requests/{cancel}/cancel", tk["cy"])
    rec["failed_key"] = new_key()
    r = api.pay(tk["cy"], "ada", 999999, key=rec["failed_key"])
    assert r.status_code == 409
    for k in ("pay", "req", "payreq", "split", "settle"):
        assert "error" not in rec[k], rec[k]
    return rec


def snapshot_view(api, w):
    """Everything observable for every seeded user."""
    out = {}
    for h, tok in w.tok.items():
        out[h] = {"me": api.me(tok), "feed": api.feed(tok, limit=200),
                  "requests": api.requests_list(tok, limit=200)}
    return out


def test_R10_1_export_import_unauthenticated(world, api):
    exp = export(api)
    assert do_import(api, exp).status_code == 204


def test_R10_2_export_shape(world, api):
    exp = export(api)
    assert exp["track"] == "pocketful"
    assert exp["format_version"] == 1 and type(exp["format_version"]) is int
    assert isinstance(exp["state"], dict)


def test_R10_3_R10_4_roundtrip_unchanged_export_204(make_world, api):
    w = make_world(op_fixture())
    populate(api, w)
    view = snapshot_view(api, w)
    r = do_import(api, export(api))
    assert r.status_code == 204 and r.content == b""
    assert snapshot_view(api, w) == view


def test_R10_15_R10_11_import_after_reset_restores_everything(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    view = snapshot_view(api, w)
    exp = export(api)
    api.reset(base_fixture(users=[user("u_zz", "zz", 1), user("u_yy", "yy", 0)]))
    assert do_import(api, exp).status_code == 204
    # old tokens valid again, everything observable identical (ids, timestamps, balances)
    assert snapshot_view(api, w) == view
    # hashed-password login still works
    assert api.login("ada@example.com") and api.login("op@example.com")
    # the reset fixture's users are gone
    r = api.post("/auth/login", json={"email": "zz@example.com", "password": PASSWORD})
    assert_error(r, 401, "unauthenticated")
    assert rec


def test_R10_12_replay_after_import_200_same_body(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    exp = export(api)
    api.reset(base_fixture())
    assert do_import(api, exp).status_code == 204
    tk = w.tok
    before = snapshot_view(api, w)
    r = api.pay(tk["ada"], "bob", 300, key=rec["pay_key"], note="café ☕",
                visibility="private")
    assert r.status_code == 200 and r.json() == rec["pay"]
    r = api.request(tk["bob"], "ada", 700, key=rec["req_key"])
    assert r.status_code == 200 and r.json() == rec["req"]
    r = api.pay_request(tk["ada"], rec["req"]["request_id"], {}, key=rec["payreq_key"])
    assert r.status_code == 200 and r.json() == rec["payreq"]
    r = api.post("/splits", tk["dee"], rec["split_key"],
                 {"amount": 1000, "participant_handles": ["dee", "ada", "cy"]})
    assert r.status_code == 200 and r.json() == rec["split"]
    r = api.post("/settlements", tk["op"], rec["settle_key"], {
        "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50},
                      {"from_handle": "cy", "to_handle": "dee", "amount": 50}]})
    assert r.status_code == 200 and r.json() == rec["settle"]
    assert snapshot_view(api, w) == before


def test_R10_12_reuse_after_import_409(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    exp = export(api)
    assert do_import(api, exp).status_code == 204
    r = api.pay(w.tok["ada"], "bob", 301, key=rec["pay_key"])
    assert_error(r, 409, "idempotency_key_reuse")


def test_R10_14_failed_key_reusable_after_import(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    exp = export(api)
    api.reset(base_fixture())
    do_import(api, exp)
    assert api.pay(w.tok["ada"], "cy", 1).status_code == 201
    r = api.pay(w.tok["cy"], "ada", 1, key=rec["failed_key"])
    assert r.status_code == 201, r.text


def test_R10_13_ids_timestamps_balances_identical_after_import(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    exp = export(api)
    api.reset(base_fixture())
    do_import(api, exp)
    feed = {p["payment_id"]: p for p in api.feed(w.tok["ada"], limit=200)["payments"]}
    assert feed[rec["pay"]["payment_id"]] == rec["pay"]
    assert feed[rec["payreq"]["payment_id"]] == rec["payreq"]
    for p in rec["settle"]["payments"]:
        if p["from_handle"] == "ada":
            assert feed[p["payment_id"]] == p
    w.assert_invariants()


def test_R11_21_import_preserves_settlements(make_world, api):
    w = make_world(op_fixture())
    rec = populate(api, w)
    exp = export(api)
    api.reset(base_fixture())
    do_import(api, exp)
    r = api.post("/settlements", w.tok["op"], new_key(),
                 {"transfers": [{"from_handle": "dee", "to_handle": "bob", "amount": 1}]})
    assert r.status_code == 201
    feed = {p["payment_id"]: p for p in api.feed(w.tok["cy"], limit=200)["payments"]}
    for p in rec["settle"]["payments"]:
        assert feed[p["payment_id"]]["settlement_id"] == rec["settle"]["settlement_id"]


def test_R10_6_import_twice_no_duplicates(make_world, api):
    w = make_world(op_fixture())
    populate(api, w)
    view = snapshot_view(api, w)
    exp = export(api)
    assert do_import(api, exp).status_code == 204
    assert do_import(api, exp).status_code == 204
    assert snapshot_view(api, w) == view


def test_R10_16_import_removes_destination_users_and_tokens(make_world, api):
    w = make_world(op_fixture())
    exp = export(api)
    newbie = api.post("/auth/signup", json={"email": "late@example.com",
                                            "password": "longenough",
                                            "display_name": "Late"}).json()["token"]
    extra_token = api.login("ada@example.com")
    api.pay(w.tok["ada"], "bob", 1)
    assert do_import(api, exp).status_code == 204
    assert_error(api.get("/me", newbie), 401, "unauthenticated")
    assert_error(api.get("/me", extra_token), 401, "unauthenticated")
    assert api.feed(w.tok["ada"])["payments"] == []
    assert api.balance(w.tok["ada"]) == 10000


def test_R10_17_reset_after_import_clears(make_world, api):
    w = make_world(op_fixture())
    populate(api, w)
    do_import(api, export(api))
    api.reset(base_fixture())
    assert_error(api.get("/me", w.tok["ada"]), 401, "unauthenticated")
    ada = api.login("ada@example.com")
    assert api.feed(ada)["payments"] == [] and api.balance(ada) == 10000


def test_R10_10_export_snapshot_isolation(make_world, api):
    w = make_world(op_fixture())
    populate(api, w)
    view = snapshot_view(api, w)
    exp = export(api)
    frozen = json.dumps(exp, sort_keys=True)
    api.pay(w.tok["ada"], "bob", 1)
    api.request(w.tok["bob"], "cy", 1)
    assert json.dumps(exp, sort_keys=True) == frozen
    second = export(api)
    assert second != exp
    do_import(api, exp)
    assert snapshot_view(api, w) == view
    third, fourth = export(api), export(api)
    assert third == fourth


@pytest.mark.parametrize("mutate", [
    lambda e: {k: v for k, v in e.items() if k != "state"},
    lambda e: {k: v for k, v in e.items() if k != "track"},
    lambda e: {k: v for k, v in e.items() if k != "format_version"},
    lambda e: {**e, "track": "other"},
    lambda e: {**e, "format_version": 2},
    lambda e: {**e, "state": {}},
    lambda e: {**e, "state": "x"},
    lambda e: {**e, "state": {"garbage": True}},
])
def test_R10_8_import_rejects_and_keeps_state(make_world, api, mutate):
    w = make_world(op_fixture())
    populate(api, w)
    good = export(api)
    view = snapshot_view(api, w)
    r = do_import(api, mutate(good))
    assert_error(r, 422, "validation_failed")
    assert snapshot_view(api, w) == view


def test_R10_7_import_invalid_json_400(world, api):
    view = api.me(world.tok["ada"])
    r = do_import(api, None, raw=b"{not json")
    assert_error(r, 400, "malformed_request")
    assert api.me(world.tok["ada"]) == view


def test_R10_19_new_ids_after_import_unique(make_world, api):
    w = make_world(op_fixture())
    populate(api, w)
    exp = export(api)
    api.reset(base_fixture())
    do_import(api, exp)
    before = {p["payment_id"] for p in api.feed(w.tok["ada"], limit=200)["payments"]}
    before_r = {q["request_id"] for q in api.requests_list(w.tok["ada"], limit=200)["requests"]}
    for _ in range(10):
        pid = api.pay(w.tok["ada"], "bob", 1).json()["payment_id"]
        assert pid not in before
        before.add(pid)
        rid = api.request(w.tok["ada"], "dee", 1).json()["request_id"]
        assert rid not in before_r
        before_r.add(rid)


def test_R10_9_export_import_within_10s(world, api):
    for _ in range(300):
        api.pay(world.tok["ada"], "bob", 1)
    t0 = time.monotonic()
    exp = export(api)
    assert do_import(api, exp).status_code == 204
    assert time.monotonic() - t0 < 10.0


def test_R6_11_export_contains_no_plaintext_password(world, api):
    api.post("/auth/signup", json={"email": "secret@example.com",
                                   "password": "Zebra-Plaintext-42", "display_name": "S"})
    raw = api.call("GET", "/_test/export", timeout=CONTROL_TIMEOUT).text
    assert "Zebra-Plaintext-42" not in raw
    assert PASSWORD not in raw
