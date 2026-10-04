"""Correction batches. Ledger R4-BAT, R4-BERR, R4-BMNY, R4-BRES, R4-SET, R4-PATH (batches)."""
import json

import pytest

from s4lib import (REVISION_KEYS, US, assert_error, batch, fingerprint, iso_ns, item, new_key, ns,
                   now_ns, refund, run_parallel)


def past(s=5):
    return iso_ns(now_ns() - s * 10 ** 9)


def settle(api, world, transfers):
    r = api.call("POST", "/settlements", world.tok["op"], new_key(), {"transfers": transfers})
    assert r.status_code == 201, r.text
    for p in r.json()["payments"]:
        world.model.add_payment(p)
    return r.json()


def members(st):
    return [m["payment_id"] for m in st["payments"]]


def two_member_settlement(api, world):
    return settle(api, world, [{"from_handle": "ada", "to_handle": "bob", "amount": 1000},
                               {"from_handle": "bob", "to_handle": "cy", "amount": 200}])


# ---------------------------------------------------------------- basics

def test_R4_BAT_1_BAT_3_BRES_1_BRES_7_operator_corrects_settlement_and_ordinary(world, api):
    st = two_member_settlement(api, world)
    p = world.pay("dee", "cy", 500)
    eff = st["committed_at"]
    items = [item(members(st)[0], 1, 600, eff, "member fix"),
             item(p["payment_id"], 1, 450, past(), "ordinary fix"),
             item(members(st)[1], 1, 0, eff, "member reversal")]
    r = batch(api, world.tok["op"], items)
    assert r.status_code == 201, r.text
    b = r.json()
    assert set(b) == {"correction_batch_id", "recorded_at", "revisions"}
    assert isinstance(b["correction_batch_id"], str) and 1 <= len(b["correction_batch_id"]) <= 64
    assert [x["payment_id"] for x in b["revisions"]] == [i["payment_id"] for i in items]
    for x, i in zip(b["revisions"], items):
        assert set(x) == REVISION_KEYS
        assert (x["revision"], x["amount"], x["reason"], x["correction_batch_id"]) == \
            (2, i["amount"], i["reason"], b["correction_batch_id"])
        assert x["effective_at"] == i["effective_at"] and x["recorded_at"] == b["recorded_at"]
    me = {h: api.me(t)["balance"] for h, t in world.tok.items()}
    assert me["ada"] == 10000 - 600 and me["bob"] == 2500 + 600 - 0
    assert me["cy"] == 1500 + 0 + 450 and me["dee"] == 5000 - 450
    assert sum(me.values()) == world.seeded_total


def test_R4_BAT_2_401_403_and_key(world, api):
    p = world.pay("ada", "bob", 100)
    items = [item(p["payment_id"], 1, 50, past())]
    assert_error(api.call("POST", "/correction-batches", None, new_key(), {"corrections": items}),
                 401, "unauthenticated")
    assert_error(batch(api, world.tok["ada"], items), 403, "forbidden")
    assert_error(api.call("POST", "/correction-batches", world.tok["ada"], new_key(),
                          {"corrections": []}), 403, "forbidden")    # 403 before body checks
    for key in (None, ""):
        r = api.call("POST", "/correction-batches", world.tok["op"], key, {"corrections": items})
        assert_error(r, 400, "missing_idempotency_key")


@pytest.mark.parametrize("corr", ["count0", "count33", "dup", "notarray", "elemnotobj", "missing"])
def test_R4_BAT_4_count_and_distinct(world, api, corr):
    ps = [world.pay("ada", "bob", 1)["payment_id"] for _ in range(2)]
    good = item(ps[0], 1, 0, past())
    body = {"count0": {"corrections": []},
            "count33": {"corrections": [item(f"p_x{i}", 1, 0, past()) for i in range(33)]},
            "dup": {"corrections": [good, dict(good)]},
            "notarray": {"corrections": good},
            "elemnotobj": {"corrections": [good, 5]},
            "missing": {}}[corr]
    r = api.call("POST", "/correction-batches", world.tok["op"], new_key(), body)
    assert_error(r, 422, "validation_failed")


def test_R4_BAT_4_thirty_two_ok(world, api):
    ps = [world.pay("ada", "bob", 1)["payment_id"] for _ in range(32)]
    r = batch(api, world.tok["op"], [item(pid, 1, 0, past()) for pid in ps])
    assert r.status_code == 201, r.text
    assert len(r.json()["revisions"]) == 32


@pytest.mark.parametrize("field,value", [
    ("expected_revision", 0), ("expected_revision", "1"), ("amount", -1), ("amount", 10 ** 9 + 1),
    ("amount", True), ("reason", ""), ("reason", "x" * 201), ("effective_at", "2026-09-20"),
    ("effective_at", None), ("effective_at", "FUTURE"),
])
def test_R4_BAT_5_BAT_12_item_field_rules(world, api, field, value):
    p = world.pay("ada", "bob", 100)
    it = item(p["payment_id"], 1, 50, past())
    it[field] = iso_ns(now_ns() + 5 * 10 ** 9) if value == "FUTURE" else value
    assert_error(batch(api, world.tok["op"], [it]), 422, "validation_failed")
    it2 = item(p["payment_id"], 1, 50, past())
    del it2["reason"]
    assert_error(batch(api, world.tok["op"], [it2]), 422, "validation_failed")


def test_R4_BAT_6_unknown_404_stale_409(world, api):
    p = world.pay("ada", "bob", 100)
    assert_error(batch(api, world.tok["op"], [item("p_nope", 1, 0, past())]), 404, "not_found")
    assert_error(batch(api, world.tok["op"], [item(p["payment_id"], 2, 0, past())]), 409,
                 "stale_revision")


def test_R4_BAT_7_operator_needs_not_be_party(world, api):
    p = world.pay("dee", "cy", 100)
    r = batch(api, world.tok["op"], [item(p["payment_id"], 1, 40, past())])
    assert r.status_code == 201, r.text
    assert api.me(world.tok["dee"])["balance"] == 4960


def test_R4_BAT_8_capture_or_refund_item_422_linked(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    f = refund(api, tk["bob"], p["payment_id"], 100).json()
    assert_error(batch(api, tk["op"], [item(f["payment_id"], 1, 50, past())]), 422,
                 "linked_payment_immutable")
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "dee", "amount": 500}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["dee"],
                   new_key(), {}).json()
    assert_error(batch(api, tk["op"], [item(cap["payment_id"], 1, 50, past())]), 422,
                 "linked_payment_immutable")


def test_R4_BAT_9_incomplete_settlement_422(world, api):
    st = two_member_settlement(api, world)
    r = batch(api, world.tok["op"], [item(members(st)[0], 1, 0, st["committed_at"])])
    assert_error(r, 422, "incomplete_settlement")


def test_R4_BAT_10_member_instants_identical_by_instant(world, api):
    st = two_member_settlement(api, world)
    t = ns(st["committed_at"]) - 3 * 10 ** 9
    a, b = members(st)
    ok = batch(api, world.tok["op"], [item(a, 1, 900, iso_ns(t)),
                                      item(b, 1, 150, iso_ns(t, 120))])   # same instant, +02:00
    assert ok.status_code == 201, ok.text
    bad = batch(api, world.tok["op"], [item(a, 2, 800, iso_ns(t)), item(b, 2, 150, iso_ns(t + US))])
    assert_error(bad, 422, "validation_failed")


def test_R4_BAT_11_unknown_fields_ignored(world, api):
    p = world.pay("ada", "bob", 100)
    it = {**item(p["payment_id"], 1, 50, past()), "colour": "red"}
    r = api.call("POST", "/correction-batches", world.tok["op"], new_key(),
                 {"corrections": [it], "memo": "x"})
    assert r.status_code == 201, r.text


def test_R4_BAT_13_refund_floor_in_batch(world, api):
    st = two_member_settlement(api, world)
    a, b = members(st)
    assert refund(api, world.tok["bob"], a, 300).status_code == 201
    r = batch(api, world.tok["op"], [item(a, 1, 299, st["committed_at"]),
                                     item(b, 1, 200, st["committed_at"])])
    assert_error(r, 422, "refund_exceeds_payment")


# ---------------------------------------------------------------- precedence

def test_R4_BERR_1_BERR_2_precedence_matrix(world, api):
    tk = world.tok
    st = two_member_settlement(api, world)
    a, b = members(st)
    p = world.pay("dee", "cy", 100)
    q = world.pay("ada", "dee", 100)
    eff = st["committed_at"]
    # first erroneous item wins (404 on item 2 beats 409 stale on item 3)
    r = batch(api, tk["op"], [item(p["payment_id"], 1, 0, past()), item("p_nope", 1, 0, past()),
                              item(q["payment_id"], 9, 0, past())])
    assert_error(r, 404, "not_found")
    r = batch(api, tk["op"], [item(q["payment_id"], 9, 0, past()), item("p_nope", 1, 0, past())])
    assert_error(r, 409, "stale_revision")
    # item error beats settlement completeness
    r = batch(api, tk["op"], [item(a, 1, 0, eff), item(p["payment_id"], 7, 0, past())])
    assert_error(r, 409, "stale_revision")
    # completeness beats insufficient funds
    r = batch(api, tk["op"], [item(a, 1, 10 ** 9, eff)])
    assert_error(r, 422, "incomplete_settlement")
    # insufficient beats historical
    r = batch(api, tk["op"], [item(p["payment_id"], 1, 10 ** 9, past())])
    assert_error(r, 409, "insufficient_funds")


def test_R4_BERR_3_within_item_order(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    refund(api, tk["bob"], p["payment_id"], 500)
    # 422 field beats 404 (same item)
    assert_error(batch(api, tk["op"], [item("p_nope", 1, -1, past())]), 422, "validation_failed")
    # stale beats refund_exceeds (same item)
    assert_error(batch(api, tk["op"], [item(p["payment_id"], 3, 10, past())]), 409,
                 "stale_revision")
    assert_error(batch(api, tk["op"], [item(p["payment_id"], 1, 10, past())]), 422,
                 "refund_exceeds_payment")


# ---------------------------------------------------------------- money

def test_R4_BMNY_1_combined_effect(world, api):
    tk = world.tok
    p1 = world.pay("bob", "ada", 2000)            # ada 12000, bob 500
    p2 = world.pay("ada", "cy", 3000)             # ada 9000, cy 4500
    world.pay("ada", "dee", 9000)                  # ada 0
    eff = past(1)
    # reversing p1 alone debits ada 2000: unaffordable
    assert_error(batch(api, tk["op"], [item(p1["payment_id"], 1, 0, eff)]), 409,
                 "insufficient_funds")
    # with p2 lowered to 500 (ada credited 2500 at the same instant) the net is affordable
    r = batch(api, tk["op"], [item(p1["payment_id"], 1, 0, eff),
                              item(p2["payment_id"], 1, 500, eff)])
    assert r.status_code == 201, r.text
    me = {h: api.me(t)["balance"] for h, t in tk.items()}
    assert (me["ada"], me["bob"], me["cy"]) == (500, 2500, 2000)
    assert sum(me.values()) == world.seeded_total


def test_R4_BMNY_2_BMNY_4_insufficient_combined_changes_nothing(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    q = world.pay("ada", "cy", 1000)
    snap = api.statement(tk["ada"]).json()["snapshot"]
    fp = fingerprint(api, world, pids=[(p["payment_id"], "ada"), (q["payment_id"], "ada")],
                     snaps=[(tk["ada"], snap)])
    key = new_key()
    r = batch(api, tk["op"], [item(p["payment_id"], 1, 4000, past()),     # ada 8000 left:
                              item(q["payment_id"], 1, 7000, past())], key)  # +3000 +6000
    assert_error(r, 409, "insufficient_funds")
    assert fingerprint(api, world, pids=[(p["payment_id"], "ada"), (q["payment_id"], "ada")],
                       snaps=[(tk["ada"], snap)]) == fp
    ok = batch(api, tk["op"], [item(p["payment_id"], 1, 900, past())], key)
    assert ok.status_code == 201, ok.text                 # the key was not claimed


def historical_setup(api, world):
    """bob receives a member, spends everything, gets it back later: reversing the member at
    its original instant overdraws bob in between while bob can afford it now."""
    st = two_member_settlement(api, world)               # bob +1000 -200
    world.pay("bob", "dee", 3300)                        # bob 0
    world.pay("dee", "bob", 3300)                        # bob 3300
    return st


def test_R4_BMNY_3_historical_overdraft_combined(world, api):
    st = historical_setup(api, world)
    a, b = members(st)
    r = batch(api, world.tok["op"], [item(a, 1, 0, st["committed_at"]),
                                     item(b, 1, 200, st["committed_at"])])
    assert_error(r, 409, "historical_overdraft")


def test_R4_BMNY_5_model_every_view(world, api):
    tk = world.tok
    st = two_member_settlement(api, world)
    p = world.pay("dee", "cy", 700)
    f = refund(api, tk["cy"], p["payment_id"], 200).json()
    world.model.add_payment(f)
    r = batch(api, tk["op"], [item(members(st)[0], 1, 600, st["committed_at"]),
                              item(members(st)[1], 1, 100, st["committed_at"]),
                              item(p["payment_id"], 1, 500, past(2))])
    assert r.status_code == 201, r.text
    for rev in r.json()["revisions"]:
        world.model.add_revision(rev)
    pts = world.model.boundaries()
    Ts = sorted({t + d for t in pts for d in (-US, 0, US)})
    Ks = [None] + sorted({k for k in world.model.recorded_points()})[-4:]
    for K in Ks:
        for T in Ts:
            s = 0
            for h, t in tk.items():
                params = {"as_of": iso_ns(T)}
                if K:
                    params["known_at"] = iso_ns(K)
                got = api.me(t, **params)
                want = world.model.view(world.uid[h], T, K or 10 ** 30)
                assert got["total"] == want["total"], (h, iso_ns(T), K, got, want)
                assert got["total"] >= 0 and got["available"] >= 0
                s += got["total"]
            assert s == world.seeded_total


# ---------------------------------------------------------------- response / revisions

def test_R4_BRES_2_shared_recorded_at_strictly_later(world, api):
    st = two_member_settlement(api, world)
    p = world.pay("dee", "cy", 100)
    single = api.correct(world.tok["dee"], p["payment_id"], 1, 90, past()).json()
    r = batch(api, world.tok["op"], [item(members(st)[0], 1, 900, st["committed_at"]),
                                     item(members(st)[1], 1, 150, st["committed_at"]),
                                     item(p["payment_id"], 2, 80, past())]).json()
    t = ns(r["recorded_at"])
    assert all(ns(x["recorded_at"]) == t for x in r["revisions"])
    assert t > ns(single["recorded_at"]) and t > ns(st["committed_at"])


def test_R4_BRES_3_batch_id_on_revisions_everywhere(world, api):
    p = world.pay("ada", "bob", 100)
    api.correct(world.tok["ada"], p["payment_id"], 1, 90, past())
    b = batch(api, world.tok["op"], [item(p["payment_id"], 2, 80, past())]).json()
    revs = api.revisions(world.tok["ada"], p["payment_id"]).json()["revisions"]
    assert [x["correction_batch_id"] for x in revs] == [None, None, b["correction_batch_id"]]
    e = next(e for e in api.statement(world.tok["ada"]).json()["entries"]
             if e["payment"]["payment_id"] == p["payment_id"])
    assert e["correction_batch_id"] == b["correction_batch_id"] and e["revision"] == 3


def test_R4_BRES_4_SET_2_receipts_unchanged(world, api):
    tk = world.tok
    key_p, key_s = new_key(), new_key()
    pay = api.call("POST", "/payments", tk["ada"], key_p, {"to_handle": "bob", "amount": 100})
    sbody = {"transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 50}]}
    st = api.call("POST", "/settlements", tk["op"], key_s, sbody)
    pid, mid = pay.json()["payment_id"], st.json()["payments"][0]["payment_id"]
    assert batch(api, tk["op"], [item(pid, 1, 10, past()),
                                 item(mid, 1, 5, st.json()["committed_at"])]).status_code == 201
    again = api.call("POST", "/payments", tk["ada"], key_p, {"to_handle": "bob", "amount": 100})
    assert again.status_code == 200 and again.json() == pay.json()
    again = api.call("POST", "/settlements", tk["op"], key_s, sbody)
    assert again.status_code == 200 and again.json() == st.json()
    feed = {x["payment_id"]: x for x in api.call("GET", "/activity", tk["ada"]).json()["payments"]}
    assert feed[pid]["amount"] == 100 and feed[mid]["amount"] == 50
    assert feed[mid]["settlement_id"] == st.json()["settlement_id"]


def test_R4_BRES_5_statements_and_snapshots(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    before = api.statement(tk["ada"], limit=200).json()
    batch(api, tk["op"], [item(p["payment_id"], 1, 400, past())])
    paged = api.statement(tk["ada"], snapshot=before["snapshot"], limit=200).json()
    assert paged["entries"] == before["entries"]
    now = api.statement(tk["ada"], limit=200).json()
    e = next(e for e in now["entries"] if e["payment"]["payment_id"] == p["payment_id"])
    assert e["payment"]["amount"] == 400 and e["revision"] == 2


def test_R4_BRES_6_PATH_3_replay_original_batch_response(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    key = new_key()
    items = [item(p["payment_id"], 1, 900, past())]
    first = batch(api, tk["op"], items, key)
    api.correct(tk["ada"], p["payment_id"], 2, 800, past())
    again = batch(api, tk["op"], items, key)
    assert again.status_code == 200 and again.json() == first.json()
    assert api.me(tk["ada"])["balance"] == 9200
    assert_error(batch(api, tk["op"], [item(p["payment_id"], 1, 1, past())], key), 409,
                 "idempotency_key_reuse")


def test_R4_PATH_1_batch_concurrent_identical(world, api):
    p = world.pay("ada", "bob", 1000)
    key = new_key()
    items = [item(p["payment_id"], 1, 600, past())]
    res = run_parallel(lambda _: batch(api, world.tok["op"], items, key), 20)
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and codes.count(200) == 19, codes
    assert len({json.dumps(r.json(), sort_keys=True) for r in res}) == 1
    assert api.me(world.tok["ada"])["balance"] == 9400


def test_R4_SET_1_member_refund_keeps_membership(world, api):
    st = two_member_settlement(api, world)
    a, b = members(st)
    f = refund(api, world.tok["bob"], a, 100)
    assert f.status_code == 201 and f.json()["settlement_id"] is None
    # the refund is not a member: the batch needs exactly the original two members
    r = batch(api, world.tok["op"], [item(a, 1, 900, st["committed_at"]),
                                     item(b, 1, 200, st["committed_at"])])
    assert r.status_code == 201, r.text
    feed = {x["payment_id"]: x for x in api.call("GET", "/activity", world.tok["bob"]).json()[
        "payments"]}
    assert feed[a]["settlement_id"] == feed[b]["settlement_id"] == st["settlement_id"]
