"""Holds, /me, POST /authorizations, fixture model. Ledger R2-HOLD, R2-ME, R2-AUTH, R2-MOD."""
from datetime import timedelta

import pytest

from s2lib import (AUTH_KEYS, CONTROL_TIMEOUT, PAYMENT_KEYS, RFC3339, assert_error, auth_rec,
                   fixture, iso, new_key, now_utc, parse_ts, user)


# ---------------------------------------------------------------- GET /me

def test_R2_ME_1_HOLD_11_me_fields_no_holds(world, api):
    m = api.me(world.tok["ada"])
    assert m == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000,
                 "total": 10000, "available": 10000, "held": 0, "currency": "EUR",
                 "minor_units": 2}


def test_R2_ME_1_MOD_5_me_shape_with_seeded_hold(make_world, api):
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 2000, note="deposit")])
    m = w.me("ada")
    assert (m["balance"], m["total"], m["available"], m["held"]) == (10000, 10000, 8000, 2000)
    b = w.me("bob")
    assert (b["total"], b["available"], b["held"]) == (2500, 2500, 0)


# ---------------------------------------------------------------- POST /authorizations

def test_R2_AUTH_3_AUTH_1_authorize_201_shape(world, api):
    r = api.authorize(world.tok["ada"], "bob", 2000, note="deposit", visibility="private")
    assert r.status_code == 201, r.text
    a = r.json()
    assert set(a) == AUTH_KEYS, set(a) ^ AUTH_KEYS
    assert (a["from_user_id"], a["from_handle"], a["to_user_id"], a["to_handle"]) == \
        ("u_ada", "ada", "u_bob", "bob")
    assert (a["amount"], a["captured_amount"], a["remaining_amount"]) == (2000, 0, 2000)
    assert (a["currency"], a["note"], a["visibility"], a["status"]) == ("EUR", "deposit",
                                                                          "private", "open")
    assert a["payment_id"] is None and a["payment_ids"] == []
    assert isinstance(a["authorization_id"], str) and len(a["authorization_id"]) <= 64
    assert RFC3339.match(a["expires_at"]) and RFC3339.match(a["created_at"])


def test_R2_AUTH_2_authorize_defaults(world, api):
    a = api.authorize(world.tok["ada"], "bob", 5).json()
    assert a["note"] == "" and a["visibility"] == "public"


@pytest.mark.parametrize("ttl", [None, 2, 3600])
def test_R2_AUTH_4_MOD_2_expires_at_is_created_plus_ttl(make_world, api, ttl):
    fx = fixture()
    if ttl is not None:
        fx["authorization_ttl_seconds"] = ttl
    w = make_world(fx)
    a = api.authorize(w.tok["ada"], "bob", 5).json()
    delta = parse_ts(a["expires_at"]) - parse_ts(a["created_at"])
    assert delta == timedelta(seconds=ttl or 600)


def test_R2_HOLD_2_authorize_holds_without_moving(world, api):
    api.authorize(world.tok["ada"], "bob", 2000)
    a, b = world.me("ada"), world.me("bob")
    assert (a["total"], a["held"], a["available"]) == (10000, 2000, 8000)
    assert (b["total"], b["held"], b["available"]) == (2500, 0, 2500)
    world.assert_invariants()


def test_R2_AUTH_5_authorize_insufficient_available_409(world, api):
    t = world.tok["bob"]
    assert api.authorize(t, "ada", 2000).status_code == 201       # available 500 left
    assert_error(api.authorize(t, "ada", 501), 409, "insufficient_funds")
    assert api.authorize(t, "ada", 500).status_code == 201        # exactly available
    assert_error(api.authorize(t, "ada", 1), 409, "insufficient_funds")
    assert world.me("bob")["held"] == 2500


@pytest.mark.parametrize("amount", [0, -1, 1_000_000_001, 1.5, "5", True, None])
def test_R2_AUTH_6_authorize_amount_rules(world, api, amount):
    assert_error(api.authorize(world.tok["ada"], "bob", amount), 422, "validation_failed")
    assert world.me("ada")["held"] == 0


def test_R2_AUTH_6_float_forms_accepted(world, api):
    r = api.call("POST", "/authorizations", world.tok["ada"], new_key(),
                 content=b'{"to_handle":"bob","amount":1e3}')
    assert r.status_code == 201 and r.json()["amount"] == 1000


def test_R2_AUTH_7_authorize_self_422(world, api):
    assert_error(api.authorize(world.tok["ada"], "ada", 5), 422, "self_payment")


def test_R2_AUTH_8_authorize_note_visibility_rules(world, api):
    t = world.tok["ada"]
    assert api.authorize(t, "bob", 1, note="n" * 200).status_code == 201
    assert_error(api.authorize(t, "bob", 1, note="n" * 201), 422, "validation_failed")
    assert_error(api.authorize(t, "bob", 1, note=None), 422, "validation_failed")
    for vis in ("friends", None, 1):
        assert_error(api.authorize(t, "bob", 1, visibility=vis), 422, "validation_failed")


def test_R2_AUTH_9_authorize_unknown_handle_404(world, api):
    assert_error(api.authorize(world.tok["ada"], "nobody", 5), 404, "not_found")


def test_R2_AUTH_10_open_authorization_not_in_feed(world, api):
    api.authorize(world.tok["ada"], "bob", 5)
    for t in world.tok.values():
        assert api.feed(t)["payments"] == []


# ---------------------------------------------------------------- held funds

def test_R2_HOLD_7_HOLD_13_held_funds_refuse_everything(world, api):
    tk = world.tok
    assert api.authorize(tk["bob"], "ada", 2000).status_code == 201  # bob: total 2500, avail 500
    assert_error(api.pay(tk["bob"], "cy", 501), 409, "insufficient_funds")
    assert_error(api.authorize(tk["bob"], "cy", 501), 409, "insufficient_funds")
    rid = api.request(tk["ada"], "bob", 501).json()["request_id"]
    assert_error(api.post(f"/requests/{rid}/pay", tk["bob"], new_key(), {}), 409,
                 "insufficient_funds")
    r = api.post("/settlements", tk["op"], new_key(),
                 {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 501}]})
    assert_error(r, 409, "insufficient_funds")
    # exactly the available amount still works (and nothing else moved)
    assert api.pay(tk["bob"], "cy", 500).status_code == 201
    m = world.me("bob")
    assert (m["total"], m["held"], m["available"]) == (2000, 2000, 0)
    world.assert_invariants()


def test_R2_HOLD_8_capture_spends_reserved_when_available_zero(world, api):
    a = api.authorize(world.tok["bob"], "ada", 2500).json()
    assert world.me("bob")["available"] == 0
    r = api.capture(world.tok["ada"], a["authorization_id"])
    assert r.status_code == 201, r.text
    m = world.me("bob")
    assert (m["total"], m["held"], m["available"]) == (0, 0, 0)
    world.assert_invariants()


def test_R2_HOLD_12_payment_immediate_no_hold(world, api):
    assert api.pay(world.tok["ada"], "bob", 100).status_code == 201
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (9900, 0, 9900)
    assert api.auths(world.tok["ada"])["authorizations"] == []


def test_R2_HOLD_14_request_pay_immediate(world, api):
    rid = api.request(world.tok["bob"], "ada", 100).json()["request_id"]
    p = api.post(f"/requests/{rid}/pay", world.tok["ada"], new_key(), {}).json()
    assert p["authorization_id"] is None and p["request_id"] == rid
    assert world.me("ada")["held"] == 0 and world.me("bob")["total"] == 2600


# ---------------------------------------------------------------- fixture model

def test_R2_MOD_1_seeded_authorization_visible_with_fixture_fields(make_world, api):
    exp = iso(now_utc() + timedelta(hours=2))
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 2000, note="deposit",
                                            visibility="private", expires_at=exp)])
    for h in ("ada", "bob"):
        items = api.auths(w.tok[h])["authorizations"]
        assert [a["authorization_id"] for a in items] == ["a_1"]
        a = items[0]
        assert (a["amount"], a["note"], a["visibility"], a["status"]) == (2000, "deposit",
                                                                            "private", "open")
        assert parse_ts(a["expires_at"]) == parse_ts(exp)
        assert a["remaining_amount"] == 2000 and a["captured_amount"] == 0
    assert api.auths(w.tok["cy"])["authorizations"] == []


def test_R2_MOD_4_seeded_expires_at_kept(make_world, api):
    exp = iso(now_utc() + timedelta(hours=3))
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 1, expires_at=exp)])
    a = api.auths(w.tok["ada"])["authorizations"][0]
    assert parse_ts(a["expires_at"]) == parse_ts(exp)


@pytest.mark.parametrize("ttl", [0, -1, 1.5, "600", True, None])
def test_R2_MOD_3_ttl_invalid_reset_422(world, api, ttl):
    fx = fixture(authorization_ttl_seconds=ttl)
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")
    assert api.me(world.tok["ada"])["total"] == 10000   # previous state kept


def test_R2_MOD_6_seeded_holds_over_balance_422_state_unchanged(world, api):
    api.pay(world.tok["ada"], "bob", 1)
    exp = iso(now_utc() + timedelta(hours=2))
    ok = fixture(authorizations=[auth_rec("a_1", "u_bob", "u_ada", 1500, expires_at=exp),
                                 auth_rec("a_2", "u_bob", "u_cy", 1000, expires_at=exp)])
    bad = fixture(authorizations=[auth_rec("a_1", "u_bob", "u_ada", 1500, expires_at=exp),
                                  auth_rec("a_2", "u_bob", "u_cy", 1001, expires_at=exp)])
    r = api.call("POST", "/_test/reset", json=bad, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")
    assert api.me(world.tok["ada"])["total"] == 9999    # nothing changed, old token valid
    api.reset(ok)                                        # sum == balance is fine
    bob = api.login("bob@example.com")
    m = api.me(bob)
    assert (m["total"], m["held"], m["available"]) == (2500, 2500, 0)


def test_R2_MOD_6_closed_or_expired_holds_do_not_count(api):
    past = iso(now_utc() - timedelta(hours=2))
    fut = iso(now_utc() + timedelta(hours=2))
    fx = fixture(authorizations=[
        auth_rec("a_1", "u_bob", "u_ada", 9999, status="voided", expires_at=fut),
        auth_rec("a_2", "u_bob", "u_ada", 9999, status="expired", expires_at=past),
        auth_rec("a_3", "u_bob", "u_ada", 9999, status="open", expires_at=past),
        auth_rec("a_4", "u_bob", "u_ada", 9999, status="captured", expires_at=fut),
    ])
    api.reset(fx)
    m = api.me(api.login("bob@example.com"))
    assert (m["total"], m["held"], m["available"]) == (2500, 0, 2500)


def test_R2_MOD_7_seeded_statuses_only_open_holds(api):
    fut = iso(now_utc() + timedelta(hours=2))
    fx = fixture(authorizations=[
        auth_rec("a_o", "u_ada", "u_bob", 100, status="open", expires_at=fut),
        auth_rec("a_c", "u_ada", "u_bob", 200, status="captured", expires_at=fut),
        auth_rec("a_v", "u_ada", "u_bob", 300, status="voided", expires_at=fut),
    ])
    api.reset(fx)
    t = api.login("ada@example.com")
    assert api.me(t)["held"] == 100
    st = {a["authorization_id"]: a["status"] for a in api.auths(t)["authorizations"]}
    assert st == {"a_o": "open", "a_c": "captured", "a_v": "voided"}


def test_R2_MOD_7_seeded_status_invalid_422(api):
    fx = fixture(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 1, status="pending")])
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


def test_R2_MOD_8_fixture_without_authorizations(api):
    fx = fixture()
    del fx["authorizations"]
    api.reset(fx)
    t = api.login("ada@example.com")
    assert api.me(t)["held"] == 0 and api.auths(t)["authorizations"] == []


@pytest.mark.parametrize("bad", [
    {"from_user_id": "u_nobody"}, {"to_user_id": "u_ada"}, {"amount": 0},
    {"visibility": "x"}, {"expires_at": "tomorrow"}, {"expires_at": None},
])
def test_R2_MOD_9_seeded_authorization_invalid_422(api, bad):
    rec = {**auth_rec("a_1", "u_ada", "u_bob", 100), **bad}
    r = api.call("POST", "/_test/reset", json=fixture(authorizations=[rec]),
                 timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


def test_R2_MOD_9_duplicate_seeded_ids_422(api):
    fx = fixture(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 1),
                                 auth_rec("a_1", "u_ada", "u_cy", 1)])
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


def test_R2_CAP_6_noncapture_payments_authorization_id_null(make_world, api):
    w = make_world(payments=[{"id": "p_s", "from_user_id": "u_ada", "to_user_id": "u_bob",
                              "amount": 1, "note": "", "visibility": "public"}])
    tk = w.tok
    direct = api.pay(tk["ada"], "bob", 1).json()
    rid = api.request(tk["bob"], "ada", 1).json()["request_id"]
    via = api.post(f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    st = api.post("/settlements", tk["op"], new_key(),
                  {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 1}]}).json()
    for p in (direct, via, st["payments"][0]):
        assert set(p) == PAYMENT_KEYS and p["authorization_id"] is None
    for p in api.feed(tk["cy"])["payments"]:
        assert set(p) == PAYMENT_KEYS and p["authorization_id"] is None


def test_R3_13_generated_authorization_ids_do_not_collide_with_seeded(make_world, api):
    seeded = [auth_rec(f"a_{i}", "u_ada", "u_bob", 1) for i in range(1, 11)]
    w = make_world(authorizations=seeded)
    ids = {a["id"] for a in seeded}
    for _ in range(12):
        aid = api.authorize(w.tok["ada"], "bob", 1).json()["authorization_id"]
        assert aid not in ids
        ids.add(aid)
