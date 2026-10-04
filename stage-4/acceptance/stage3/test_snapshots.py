"""Stable statement pagination. Ledger R3-SNAP."""
import threading

import pytest

from s3lib import US, assert_error, base_fixture, iso_ns, new_key, ns, now_ns, run_parallel


def entries_via(api, tok, snap, limit, total):
    out, off = [], 0
    while off < total + limit:
        b = api.statement(tok, snapshot=snap, limit=limit, offset=off).json()
        out += b["entries"]
        off += limit
        if not b["has_more"]:
            break
    return out


def test_R3_SNAP_1_token_returned(world, api):
    a = api.statement(world.tok["ada"]).json()
    b = api.statement(world.tok["ada"]).json()
    assert isinstance(a["snapshot"], str) and a["snapshot"]
    assert a["snapshot"] != b["snapshot"]                  # every first read mints a token


def test_R3_SNAP_2_SNAP_3_SNAP_10_frozen_after_every_kind_of_write(world, api):
    tk = world.tok
    for i in range(4):
        world.pay("ada", "bob", 10 + i)
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "bob", "amount": 300}).json()
    first = api.statement(tk["ada"], limit=2).json()
    full = api.statement(tk["ada"], limit=200).json()
    frozen = full["entries"]
    snap = first["snapshot"]
    # writes of every kind after the first read
    world.pay("ada", "dee", 7)
    world.pay("bob", "ada", 5)
    p = frozen[2]["payment"]["payment_id"]
    r = world.correct("ada", p, 1, 1, iso_ns(ns(world.fx["payments"][0]["created_at"]) + US))
    assert r.status_code == 201, r.text                     # backdated into the window
    api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"], new_key(),
             {"amount": 100})
    api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 3}]})
    paged = entries_via(api, tk["ada"], snap, 2, len(frozen))
    assert paged == frozen            # identical to the read taken before the writes
    page0 = api.statement(tk["ada"], snapshot=snap, limit=2, offset=0).json()
    assert page0["entries"] == first["entries"]
    assert (page0["opening_balance"], page0["closing_balance"]) == \
        (first["opening_balance"], first["closing_balance"])
    assert len(paged) == len(frozen)


def test_R3_SNAP_4_snapshot_with_window_params_422(world, api):
    snap = api.statement(world.tok["ada"]).json()["snapshot"]
    t = iso_ns(now_ns())
    for extra in ({"from": t}, {"to": t}, {"known_at": t}, {"from": ""}, {"known_at": ""}):
        assert_error(api.statement(world.tok["ada"], snapshot=snap, **extra), 422,
                     "validation_failed")


def test_R3_SNAP_5_SNAP_6_unknown_other_user_reset_import(world, api):
    tk = world.tok
    snap = api.statement(tk["ada"]).json()["snapshot"]
    assert_error(api.statement(tk["ada"], snapshot="nope-" + new_key()), 404, "not_found")
    assert_error(api.statement(tk["bob"], snapshot=snap), 404, "not_found")
    # an import does not end a token (D-50, L8(1)) ...
    exported = api.export()
    assert api.import_(exported).status_code == 204
    assert api.statement(tk["ada"], snapshot=snap).status_code == 200
    # ... a reset ends it ...
    api.reset(base_fixture())
    ada = api.login("ada@example.com")
    assert_error(api.statement(ada, snapshot=snap), 404, "not_found")
    # ... and a later import does not bring it back
    assert api.import_(api.export()).status_code == 204
    assert_error(api.statement(ada, snapshot=snap), 404, "not_found")


def test_R3_SNAP_7_paging_has_more_and_beyond_end(world, api):
    for i in range(5):
        world.pay("ada", "bob", 1 + i)
    first = api.statement(world.tok["ada"], limit=3).json()      # 7 entries total
    snap = first["snapshot"]
    assert first["has_more"] is True
    p2 = api.statement(world.tok["ada"], snapshot=snap, limit=3, offset=3).json()
    assert len(p2["entries"]) == 3 and p2["has_more"] is True
    p3 = api.statement(world.tok["ada"], snapshot=snap, limit=3, offset=6).json()
    assert len(p3["entries"]) == 1 and p3["has_more"] is False
    p4 = api.statement(world.tok["ada"], snapshot=snap, limit=3, offset=50).json()
    assert p4["entries"] == [] and p4["has_more"] is False
    assert p4["opening_balance"] == first["opening_balance"]


def test_R3_SNAP_8_unknown_params_ignored(world, api):
    snap = api.statement(world.tok["ada"]).json()["snapshot"]
    r = api.statement(world.tok["ada"], snapshot=snap, colour="teal", page="2")
    assert r.status_code == 200


def test_R3_SNAP_11_paging_validation(world, api):
    snap = api.statement(world.tok["ada"]).json()["snapshot"]
    for bad in ({"limit": "0"}, {"limit": "201"}, {"offset": "-1"}, {"limit": "4.0"}):
        assert_error(api.statement(world.tok["ada"], snapshot=snap, **bad), 422,
                     "validation_failed")


def test_R3_SNAP_9_concurrent_writes_while_paging(world, api):
    for i in range(6):
        world.pay("ada", "bob", 1 + i)
    first = api.statement(world.tok["ada"], limit=200).json()
    snap = first["snapshot"]
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            api.pay(world.tok["bob"], "ada", 1)
            api.pay(world.tok["ada"], "dee", 1)

    th = threading.Thread(target=writer)
    th.start()
    try:
        for _ in range(15):
            again = api.statement(world.tok["ada"], snapshot=snap, limit=200).json()
            assert again["entries"] == first["entries"]
            assert again["closing_balance"] == first["closing_balance"]
    finally:
        stop.set()
        th.join()
