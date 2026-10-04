"""GET /statement and known_at selection. Ledger R3-ST, R3-KN."""
from datetime import timedelta

import pytest

from s3lib import (ENTRY_KEYS, PAYMENT_KEYS, US, assert_error, iso_ns, new_key, ns, now_ns)


def ids(entries):
    return [e["payment"]["payment_id"] for e in entries]


def test_R3_ST_4_ST_13_KN_7_shape(world, api):
    world.pay("ada", "bob", 100)
    r = api.statement(world.tok["ada"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert {"opening_balance", "entries", "closing_balance", "has_more", "snapshot"} <= set(b)
    assert isinstance(b["snapshot"], str) and b["snapshot"]
    for e in b["entries"]:
        assert set(e) == ENTRY_KEYS, set(e) ^ ENTRY_KEYS
        assert set(e["payment"]) == PAYMENT_KEYS


def test_R3_ST_1_defaults_full_history_to_now(world, api):
    p = world.pay("ada", "bob", 100)
    b = api.statement(world.tok["ada"]).json()
    assert b["opening_balance"] == 12000
    assert ids(b["entries"]) == ["p_s1", "p_s2", p["payment_id"]]
    assert b["closing_balance"] == 9900 and b["has_more"] is False


def test_R3_ST_3_half_open_window(world, api):
    s1, s2 = (world.fx["payments"][i]["created_at"] for i in (0, 1))
    b = api.statement(world.tok["ada"], **{"from": s1, "to": s2}).json()
    assert ids(b["entries"]) == ["p_s1"]                 # at from: in; at to: out
    assert (b["opening_balance"], b["closing_balance"]) == (12000, 11500)
    b = api.statement(world.tok["ada"], **{"from": iso_ns(ns(s1) + US), "to": iso_ns(ns(s2) + US)}
                      ).json()
    assert ids(b["entries"]) == ["p_s2"]
    assert (b["opening_balance"], b["closing_balance"]) == (11500, 10000)


def test_R3_ST_5_ST_8_ST_11_order_sign_running_balance(world, api):
    world.pay("bob", "ada", 700)
    world.pay("ada", "dee", 300)
    b = api.statement(world.tok["ada"]).json()
    deltas = [e["delta"] for e in b["entries"]]
    assert deltas == [-500, -1500, 700, -300]
    run = b["opening_balance"]
    for e in b["entries"]:
        run += e["delta"]
        assert e["balance_after"] == run
    times = [ns(e["effective_at"]) for e in b["entries"]]
    assert times == sorted(times)


def test_R3_ST_6_opening_closing_match_me_as_of(world, api):
    p = world.pay("ada", "bob", 100)
    t = ns(p["created_at"])
    frm, to = iso_ns(ns(world.fx["payments"][1]["created_at"])), iso_ns(t + US)
    b = api.statement(world.tok["ada"], **{"from": frm, "to": to}).json()
    assert b["opening_balance"] == api.me(world.tok["ada"], as_of=iso_ns(ns(frm) - US))["balance"]
    assert b["closing_balance"] == api.me(world.tok["ada"], as_of=iso_ns(ns(to) - US))["balance"]


def test_R3_ST_7_ST_9_pagination_does_not_change_balances(world, api):
    for i in range(9):
        world.pay("ada", "bob", 10 + i)
    full = api.statement(world.tok["ada"], limit=200).json()
    for limit in (1, 2, 3, 5):
        first, entries = api.statement_all(world.tok["ada"], limit=limit)
        assert entries == full["entries"]
        assert (first["opening_balance"], first["closing_balance"]) == \
            (full["opening_balance"], full["closing_balance"])
    assert full["opening_balance"] + sum(e["delta"] for e in full["entries"]) == \
        full["closing_balance"]
    page = api.statement(world.tok["ada"], limit=2, offset=4).json()
    assert page["entries"] == full["entries"][4:6]
    assert page["opening_balance"] == full["opening_balance"]


def test_R3_ST_10_only_own_payments(world, api):
    world.pay("dee", "cy", 5)                                   # public, ada not a party
    b = api.statement(world.tok["ada"]).json()
    assert "p_s2" in ids(b["entries"])                          # own private payment
    assert all(world.tok and e["payment"]["from_user_id"] == "u_ada"
               or e["payment"]["to_user_id"] == "u_ada" for e in b["entries"])
    assert len(api.statement(world.tok["op"]).json()["entries"]) == 0


def test_R3_ST_2_limit_offset_rules(world, api):
    t = world.tok["ada"]
    for bad in ("0", "201", "4.0", "+4", "1e9", "-1"):
        assert_error(api.statement(t, limit=bad), 422, "validation_failed")
    assert_error(api.statement(t, offset="-1"), 422, "validation_failed")
    b = api.statement(t, offset="9" * 30).json()
    assert b["entries"] == [] and b["has_more"] is False
    assert api.statement(t, limit=1).json()["has_more"] is True


def test_R3_ST_12_window_validation(world, api):
    t = world.tok["ada"]
    s1 = world.fx["payments"][0]["created_at"]
    for params in ({"from": "x"}, {"to": "2026-01-01"}, {"from": ""}, {"to": ""},
                   {"from": iso_ns(ns(s1) + US), "to": s1}):
        assert_error(api.statement(t, **params), 422, "validation_failed")
    b = api.statement(t, **{"from": s1, "to": s1}).json()
    assert b["entries"] == [] and b["opening_balance"] == b["closing_balance"] == 12000


def test_R3_ST_14_settlement_members_and_captures_in_statement(world, api):
    tk = world.tok
    st = api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 10},
        {"from_handle": "bob", "to_handle": "ada", "amount": 4}]}).json()
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "bob", "amount": 50}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                   new_key(), {"amount": 20}).json()
    b = api.statement(tk["ada"]).json()
    got = ids(b["entries"])
    for m in st["payments"]:
        assert got.count(m["payment_id"]) == 1
    assert got.count(cap["payment_id"]) == 1
    e = next(e for e in b["entries"] if e["payment"]["payment_id"] == cap["payment_id"])
    assert e["payment"]["authorization_id"] == a["authorization_id"] and e["delta"] == -20
    m1, m2 = (next(e for e in b["entries"] if e["payment"]["payment_id"] == m["payment_id"])
              for m in st["payments"])
    assert m1["effective_at"] == m2["effective_at"]


# ---------------------------------------------------------------- known_at

def test_R3_KN_1_KN_3_KN_11_known_at_and_defaults(world, api):
    p = world.pay("ada", "bob", 100)
    t = ns(p["created_at"])
    me_now = api.me(world.tok["ada"])
    assert api.me(world.tok["ada"], known_at=iso_ns(now_ns() + 10 ** 9))["balance"] == \
        me_now["balance"] == 9900
    assert api.me(world.tok["ada"], known_at=iso_ns(t - US))["balance"] == 10000
    assert api.me(world.tok["ada"], known_at=iso_ns(t))["balance"] == 9900
    b = api.statement(world.tok["ada"], known_at=iso_ns(t - US)).json()
    assert p["payment_id"] not in ids(b["entries"]) and b["known_at"] == iso_ns(t - US)


def correct_ok(world, frm, pid, expected, amount, eff, reason="fix"):
    r = world.correct(frm, pid, expected, amount, eff, reason)
    assert r.status_code == 201, r.text
    return r.json()


def test_R3_KN_2_KN_4_two_time_matrix(world, api):
    p = world.pay("ada", "bob", 1000)
    tc = ns(p["created_at"])
    eff = iso_ns(tc - 3600 * 10 ** 9)                       # backdated one hour
    c = correct_ok(world, "ada", p["payment_id"], 1, 400, eff)
    rec = ns(c["recorded_at"])
    t = world.tok["ada"]
    # known before the correction: the original 1000 at tc
    assert api.me(t, known_at=iso_ns(rec - US), as_of=iso_ns(tc))["balance"] == 9000
    assert api.me(t, known_at=iso_ns(rec - US), as_of=iso_ns(tc - US))["balance"] == 10000
    # known after: 400 effective an hour earlier
    assert api.me(t, known_at=iso_ns(rec), as_of=eff)["balance"] == 9600
    assert api.me(t, known_at=iso_ns(rec), as_of=iso_ns(ns(eff) - US))["balance"] == 10000
    assert api.me(t)["balance"] == 9600
    # known_at before the payment existed: nothing
    assert api.me(t, known_at=iso_ns(tc - US), as_of=iso_ns(tc))["balance"] == 10000


def test_R3_KN_6_KN_8_KN_10_KN_12_backdated_correction_moves_entry(world, api):
    p = world.pay("ada", "bob", 1000)
    s1 = world.fx["payments"][0]["created_at"]
    s2 = world.fx["payments"][1]["created_at"]
    eff = iso_ns((ns(s1) + ns(s2)) // 2)                    # between the two seeded payments
    correct_ok(world, "ada", p["payment_id"], 1, 400, eff)
    b = api.statement(world.tok["ada"]).json()
    assert ids(b["entries"]) == ["p_s1", p["payment_id"], "p_s2"]
    e = b["entries"][1]
    assert e["payment"]["amount"] == 400 and e["delta"] == -400 and e["revision"] == 2
    assert ns(e["effective_at"]) == ns(eff)
    win = api.statement(world.tok["ada"], **{"from": iso_ns(ns(s2)), "to": iso_ns(now_ns())}
                        ).json()
    assert p["payment_id"] not in ids(win["entries"])         # moved out of this window
    feed = api.call("GET", "/activity", world.tok["ada"]).json()["payments"]
    assert next(x for x in feed if x["payment_id"] == p["payment_id"])["amount"] == 1000


def test_R3_KN_5_future_instants_allowed(world, api):
    fut = iso_ns(now_ns() + 3600 * 10 ** 9)
    assert api.me(world.tok["ada"], as_of=fut, known_at=fut)["balance"] == 10000
    b = api.statement(world.tok["ada"], **{"to": fut, "known_at": fut})
    assert b.status_code == 200
