"""Capture, void, list, expiry. Ledger R2-CAP, R2-VOID, R2-LIST, R2-EXP, R2-HOLD.1/3/9/10."""
import time
from datetime import timedelta

import pytest

from s2lib import (AUTH_KEYS, PAYMENT_KEYS, assert_error, auth_rec, fixture, iso, new_key,
                   now_utc, run_parallel)


def mk(api, w, payer="ada", to="bob", amount=2000, **f):
    r = api.authorize(w.tok[payer], to, amount, **f)
    assert r.status_code == 201, r.text
    return r.json()


def get_auth(api, w, h, aid):
    for a in api.auths(w.tok[h], limit=200)["authorizations"]:
        if a["authorization_id"] == aid:
            return a
    raise AssertionError("authorization not listed")


# ---------------------------------------------------------------- capture basics

def test_R2_CAP_4_capture_returns_payment_shape(world, api):
    a = mk(api, world, note="deposit", visibility="private")
    r = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 1500})
    assert r.status_code == 201, r.text
    p = r.json()
    assert set(p) == PAYMENT_KEYS, set(p) ^ PAYMENT_KEYS
    assert p["authorization_id"] == a["authorization_id"]
    assert p["request_id"] is None and p["settlement_id"] is None
    assert (p["from_user_id"], p["to_user_id"], p["amount"]) == ("u_ada", "u_bob", 1500)
    assert (p["note"], p["visibility"], p["currency"]) == ("deposit", "private", "EUR")


def test_R2_CAP_7_HOLD_1_partial_final_capture_releases_rest(world, api):
    a = mk(api, world)
    assert world.me("ada")["available"] == 8000
    api.capture(world.tok["bob"], a["authorization_id"], {"amount": 1500})
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (8500, 0, 8500)
    assert world.me("bob")["total"] == 4000
    got = get_auth(api, world, "ada", a["authorization_id"])
    assert (got["status"], got["captured_amount"], got["remaining_amount"]) == ("captured",
                                                                                  1500, 0)
    world.assert_invariants()


def test_R2_CAP_2_capture_default_amount_is_remaining(world, api):
    a = mk(api, world)
    p = api.capture(world.tok["bob"], a["authorization_id"]).json()
    assert p["amount"] == 2000
    b = mk(api, world)
    api.capture(world.tok["bob"], b["authorization_id"], {"amount": 700, "final": False})
    p = api.capture(world.tok["bob"], b["authorization_id"]).json()
    assert p["amount"] == 1300


def test_R2_CAP_3_empty_vs_explicit_amount_reuse_409(world, api):
    a = mk(api, world)
    key = new_key()
    assert api.capture(world.tok["bob"], a["authorization_id"], {}, key=key).status_code == 201
    r = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 2000}, key=key)
    assert_error(r, 409, "idempotency_key_reuse")
    r = api.capture(world.tok["bob"], a["authorization_id"], {"final": True}, key=key)
    assert_error(r, 409, "idempotency_key_reuse")


def test_R2_HOLD_10_capture_replay_moves_once(world, api):
    a = mk(api, world)
    key = new_key()
    first = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 500}, key=key)
    again = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 500}, key=key)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert world.me("bob")["total"] == 3000
    world.assert_invariants()


def test_R2_CAP_8_CAP_17_closed_cannot_capture(world, api):
    a = mk(api, world)
    api.capture(world.tok["bob"], a["authorization_id"], {"amount": 100})
    assert_error(api.capture(world.tok["bob"], a["authorization_id"]), 409,
                 "authorization_not_open")
    v = mk(api, world)
    api.void(world.tok["ada"], v["authorization_id"])
    assert_error(api.capture(world.tok["bob"], v["authorization_id"]), 409,
                 "authorization_not_open")
    world.assert_invariants()


def test_R2_CAP_9_HOLD_3_nonfinal_keeps_remainder_held(world, api):
    a = mk(api, world)
    r = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 700, "final": False})
    assert r.status_code == 201
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (9300, 1300, 8000)
    got = get_auth(api, world, "bob", a["authorization_id"])
    assert (got["status"], got["captured_amount"], got["remaining_amount"]) == ("open", 700,
                                                                                  1300)


@pytest.mark.parametrize("final", [None, 0, "false", 1])
def test_R2_CAP_9_final_wrong_type_400(world, api, final):
    a = mk(api, world)
    r = api.capture(world.tok["bob"], a["authorization_id"], {"amount": 1, "final": final})
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})
    assert world.me("ada")["held"] == 2000


def test_R2_CAP_10_nonfinal_sequence_closes_at_full(world, api):
    a = mk(api, world)
    aid = a["authorization_id"]
    for amt in (500, 500, 1000):
        assert api.capture(world.tok["bob"], aid, {"amount": amt, "final": False}).status_code \
            == 201
    got = get_auth(api, world, "ada", aid)
    assert (got["status"], got["captured_amount"], got["remaining_amount"]) == ("captured",
                                                                                  2000, 0)
    assert world.me("ada")["held"] == 0
    assert_error(api.capture(world.tok["bob"], aid, {"amount": 1, "final": False}), 409,
                 "authorization_not_open")


def test_R2_CAP_11_nonfinal_then_final_releases_rest(world, api):
    aid = mk(api, world)["authorization_id"]
    api.capture(world.tok["bob"], aid, {"amount": 700, "final": False})
    api.capture(world.tok["bob"], aid, {"amount": 300, "final": True})
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (9000, 0, 9000)
    assert get_auth(api, world, "ada", aid)["status"] == "captured"


def test_R2_CAP_12_CAP_18_exceeds_compares_remaining(world, api):
    aid = mk(api, world)["authorization_id"]
    assert_error(api.capture(world.tok["bob"], aid, {"amount": 2001}), 422,
                 "capture_exceeds_authorization")
    api.capture(world.tok["bob"], aid, {"amount": 700, "final": False})
    assert_error(api.capture(world.tok["bob"], aid, {"amount": 1301}), 422,
                 "capture_exceeds_authorization")
    assert world.me("ada")["held"] == 1300
    assert api.capture(world.tok["bob"], aid, {"amount": 1300}).status_code == 201


def test_R2_CAP_13_cumulative_fields_after_each_capture(world, api):
    aid = mk(api, world)["authorization_id"]
    pids = []
    for amt, cum in ((300, 300), (200, 500)):
        p = api.capture(world.tok["bob"], aid, {"amount": amt, "final": False}).json()
        pids.append(p["payment_id"])
        got = get_auth(api, world, "ada", aid)
        assert got["captured_amount"] == cum
        assert got["payment_id"] == p["payment_id"]
        assert got["payment_ids"] == pids


def test_R2_CAP_14_remaining_amount_everywhere(world, api):
    a = mk(api, world)
    assert a["remaining_amount"] == 2000
    v = api.void(world.tok["ada"], a["authorization_id"]).json()
    assert v["remaining_amount"] == 0 and set(v) == AUTH_KEYS
    b = mk(api, world)
    api.capture(world.tok["bob"], b["authorization_id"], {"amount": 1})
    assert get_auth(api, world, "ada", b["authorization_id"])["remaining_amount"] == 0


def test_R2_CAP_16_replay_returns_original_even_after_more_captures(world, api):
    aid = mk(api, world)["authorization_id"]
    key = new_key()
    first = api.capture(world.tok["bob"], aid, {"amount": 100, "final": False}, key=key).json()
    api.capture(world.tok["bob"], aid, {"amount": 100, "final": False})
    again = api.capture(world.tok["bob"], aid, {"amount": 100, "final": False}, key=key)
    assert again.status_code == 200 and again.json() == first
    assert world.me("bob")["total"] == 2700


@pytest.mark.parametrize("amount", [0, -1, 1.5, "5", True, None])
def test_R2_CAP_19_capture_amount_rules(world, api, amount):
    aid = mk(api, world)["authorization_id"]
    assert_error(api.capture(world.tok["bob"], aid, {"amount": amount}), 422, "validation_failed")


def test_R2_CAP_20_CAP_1_VOID_5_payer_or_third_party_capture_403(world, api):
    aid = mk(api, world)["authorization_id"]
    for h in ("ada", "cy", "op"):
        assert_error(api.capture(world.tok[h], aid), 403, "forbidden")
    assert world.me("ada")["held"] == 2000


def test_R2_CAP_21_unknown_authorization_404(world, api):
    assert_error(api.capture(world.tok["bob"], "a_nope"), 404, "not_found")


def test_R2_CAP_22_capture_precedence(world, api):
    aid = mk(api, world)["authorization_id"]
    # body validation before 404/403
    assert_error(api.capture(world.tok["cy"], "a_nope", {"amount": 0}), 422, "validation_failed")
    # 403 before not_open
    api.capture(world.tok["bob"], aid)
    assert_error(api.capture(world.tok["ada"], aid), 403, "forbidden")
    # not_open before exceeds
    assert_error(api.capture(world.tok["bob"], aid, {"amount": 999999}), 409,
                 "authorization_not_open")
    # claimed key before validation
    b = mk(api, world)["authorization_id"]
    key = new_key()
    api.capture(world.tok["bob"], b, {"amount": 5}, key=key)
    assert_error(api.capture(world.tok["bob"], b, {"amount": -5}, key=key), 409,
                 "idempotency_key_reuse")


def test_R2_CAP_5_capture_payment_in_feed_by_rule(world, api):
    pub = mk(api, world, visibility="public")["authorization_id"]
    priv = mk(api, world, visibility="private")["authorization_id"]
    p1 = api.capture(world.tok["bob"], pub, {"amount": 10}).json()["payment_id"]
    p2 = api.capture(world.tok["bob"], priv, {"amount": 10}).json()["payment_id"]
    third = {p["payment_id"] for p in api.feed(world.tok["cy"])["payments"]}
    party = {p["payment_id"] for p in api.feed(world.tok["ada"])["payments"]}
    assert third == {p1} and party == {p1, p2}


def test_R2_HOLD_9_cumulative_never_exceeds_concurrent(world, api):
    aid = mk(api, world, amount=1000)["authorization_id"]
    res = run_parallel(lambda i: api.capture(world.tok["bob"], aid,
                                             {"amount": 300, "final": False}), 20)
    codes = [r.status_code for r in res]
    assert codes.count(201) == 3, codes
    got = get_auth(api, world, "ada", aid)
    assert got["captured_amount"] == 900 and got["remaining_amount"] == 100
    assert all(c in (201, 409, 422) for c in codes)
    world.assert_invariants()


# ---------------------------------------------------------------- void

def test_R2_VOID_1_VOID_2_void_by_payer_no_key(world, api):
    aid = mk(api, world)["authorization_id"]
    r = api.void(world.tok["ada"], aid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "voided"
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (10000, 0, 10000)


def test_R2_VOID_3_void_twice_200(world, api):
    aid = mk(api, world)["authorization_id"]
    api.void(world.tok["ada"], aid)
    r = api.void(world.tok["ada"], aid)
    assert r.status_code == 200 and r.json()["status"] == "voided"


def test_R2_VOID_4_void_captured_or_expired_409(make_world, api):
    past = iso(now_utc() - timedelta(hours=2))
    w = make_world(authorizations=[auth_rec("a_x", "u_ada", "u_bob", 10, status="expired",
                                            expires_at=past),
                                   auth_rec("a_y", "u_ada", "u_bob", 10, status="open",
                                            expires_at=past)])
    aid = mk(api, w)["authorization_id"]
    api.capture(w.tok["bob"], aid)
    for x in (aid, "a_x", "a_y"):
        assert_error(api.void(w.tok["ada"], x), 409, "authorization_not_open")


def test_R2_VOID_5_receiver_or_third_party_void_403(world, api):
    aid = mk(api, world)["authorization_id"]
    for h in ("bob", "cy"):
        assert_error(api.void(world.tok[h], aid), 403, "forbidden")


def test_R2_VOID_6_unknown_void_404(world, api):
    assert_error(api.void(world.tok["ada"], "a_nope"), 404, "not_found")


def test_R2_CAP_15_void_after_nonfinal_keeps_captures(world, api):
    aid = mk(api, world)["authorization_id"]
    p = api.capture(world.tok["bob"], aid, {"amount": 700, "final": False}).json()
    v = api.void(world.tok["ada"], aid).json()
    assert (v["status"], v["captured_amount"], v["remaining_amount"]) == ("voided", 700, 0)
    assert v["payment_ids"] == [p["payment_id"]]
    m = world.me("ada")
    assert (m["total"], m["held"], m["available"]) == (9300, 0, 9300)
    assert p["payment_id"] in {x["payment_id"] for x in api.feed(world.tok["ada"])["payments"]}


# ---------------------------------------------------------------- list

def test_R2_LIST_1_only_own_authorizations(world, api):
    mk(api, world, "ada", "bob")
    mk(api, world, "dee", "cy", 5)
    assert len(api.auths(world.tok["ada"])["authorizations"]) == 1
    assert len(api.auths(world.tok["bob"])["authorizations"]) == 1
    assert api.auths(world.tok["op"])["authorizations"] == []


def test_R2_LIST_6_list_shape(world, api):
    mk(api, world)
    body = api.auths(world.tok["ada"])
    assert set(body) == {"authorizations", "has_more"} and body["has_more"] is False
    assert set(body["authorizations"][0]) == AUTH_KEYS


def test_R2_LIST_2_newest_first(world, api):
    ids = []
    for i in range(3):
        ids.append(mk(api, world, amount=10 + i)["authorization_id"])
        if i < 2:
            time.sleep(1.1)  # distinct created_at seconds
    got = [a["authorization_id"] for a in api.auths(world.tok["ada"])["authorizations"]]
    assert got == list(reversed(ids))


def test_R2_LIST_3_direction_filter(world, api):
    out = mk(api, world, "ada", "bob", 5)["authorization_id"]
    inc = mk(api, world, "dee", "ada", 5)["authorization_id"]
    t = world.tok["ada"]
    assert [a["authorization_id"] for a in api.auths(t, direction="outgoing")["authorizations"]] \
        == [out]
    assert [a["authorization_id"] for a in api.auths(t, direction="incoming")["authorizations"]] \
        == [inc]


def test_R2_LIST_4_status_filter_all_four(make_world, api):
    past = iso(now_utc() - timedelta(hours=2))
    w = make_world(authorizations=[auth_rec("a_e", "u_ada", "u_bob", 1, status="open",
                                            expires_at=past)])
    o = mk(api, w, amount=1)["authorization_id"]
    c = mk(api, w, amount=1)["authorization_id"]
    api.capture(w.tok["bob"], c)
    v = mk(api, w, amount=1)["authorization_id"]
    api.void(w.tok["ada"], v)
    for status, aid in (("open", o), ("captured", c), ("voided", v), ("expired", "a_e")):
        got = api.auths(w.tok["ada"], status=status)["authorizations"]
        assert [a["authorization_id"] for a in got] == [aid], status
        assert got[0]["status"] == status


def test_R2_LIST_4_unknown_direction_status_422(world, api):
    for params in ({"direction": "both"}, {"direction": ""}, {"status": "closed"},
                   {"status": "OPEN"}):
        assert_error(api.get("/authorizations", world.tok["ada"], params=params), 422,
                     "validation_failed")


def test_R2_LIST_5_limit_offset_has_more(world, api):
    for _ in range(4):
        mk(api, world, amount=1)
    t = world.tok["ada"]
    assert api.auths(t, limit=4)["has_more"] is False
    assert api.auths(t, limit=3)["has_more"] is True
    for bad in ("0", "201", "4.0", "+4", "1e9"):
        assert_error(api.get("/authorizations", t, params={"limit": bad}), 422,
                     "validation_failed")
    assert_error(api.get("/authorizations", t, params={"offset": "-1"}), 422,
                 "validation_failed")
    assert api.auths(t, offset="1" * 50) == {"authorizations": [], "has_more": False}


# ---------------------------------------------------------------- expiry

def test_R2_EXP_1_expired_holds_nothing(make_world, api):
    past = iso(now_utc() - timedelta(hours=1, minutes=1))
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 9000, status="open",
                                            expires_at=past)])
    m = w.me("ada")
    assert (m["held"], m["available"]) == (0, 10000)
    assert api.auths(w.tok["ada"])["authorizations"][0]["status"] == "expired"


def ttl_world(make_world, ttl=2):
    return make_world(fixture(authorization_ttl_seconds=ttl))


def test_R2_EXP_2_EXP_3_HOLD_4_expiry_releases_without_any_request(make_world, api):
    w = ttl_world(make_world)
    a = mk(api, w, "bob", "ada", 2500)
    assert w.me("bob")["available"] == 0
    time.sleep(3.2)  # pass the deadline with no request in between
    m = w.me("bob")
    assert (m["total"], m["held"], m["available"]) == (2500, 0, 2500)
    got = get_auth(api, w, "bob", a["authorization_id"])
    assert got["status"] == "expired" and got["remaining_amount"] == 0
    assert api.pay(w.tok["bob"], "cy", 2500).status_code == 201


def test_R2_EXP_2_write_reflects_expiry_first(make_world, api):
    w = ttl_world(make_world)
    mk(api, w, "bob", "ada", 2500)
    time.sleep(3.2)
    # the very first request after the deadline is a write that needs the released funds
    assert api.pay(w.tok["bob"], "cy", 2500).status_code == 201


def test_R2_EXP_5_capture_after_expiry_409_expired(make_world, api):
    w = ttl_world(make_world)
    aid = mk(api, w, amount=100)["authorization_id"]
    time.sleep(3.2)
    assert_error(api.capture(w.tok["bob"], aid), 409, "authorization_expired")


def test_R2_EXP_5_seeded_expired_capture_409(make_world, api):
    past = iso(now_utc() - timedelta(hours=2))
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 10, status="expired",
                                            expires_at=past)])
    assert_error(api.capture(w.tok["bob"], "a_1"), 409,
                 {"authorization_expired", "authorization_not_open"})


def test_R2_EXP_6_clock_expired_filters_as_expired(make_world, api):
    w = ttl_world(make_world)
    aid = mk(api, w, amount=5)["authorization_id"]
    time.sleep(3.2)
    assert api.auths(w.tok["ada"], status="open")["authorizations"] == []
    got = api.auths(w.tok["ada"], status="expired")["authorizations"]
    assert [a["authorization_id"] for a in got] == [aid]


def test_R2_EXP_3_CAP_15_partial_nonfinal_then_expiry_releases_only_remainder(make_world, api):
    w = ttl_world(make_world, ttl=3)
    aid = mk(api, w, amount=2000)["authorization_id"]
    p = api.capture(w.tok["bob"], aid, {"amount": 700, "final": False}).json()
    time.sleep(4.2)
    m = w.me("ada")
    assert (m["total"], m["held"], m["available"]) == (9300, 0, 9300)
    got = get_auth(api, w, "ada", aid)
    assert (got["status"], got["captured_amount"], got["payment_ids"]) == ("expired", 700,
                                                                           [p["payment_id"]])
    w.assert_invariants()
