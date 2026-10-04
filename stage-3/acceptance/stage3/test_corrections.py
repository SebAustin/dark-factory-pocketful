"""Corrections, money movement, overdraft, revisions endpoint, linked payments.

Ledger R3-COR, R3-MNY, R3-RVL, R3-REV, R3-SET.
"""
import json
from datetime import timedelta

import pytest

from s3lib import (REVISION_KEYS, US, assert_error, iso_ns, new_key, ns, now_ns, run_parallel,
                   user)


def past(seconds=5):
    return iso_ns(now_ns() - seconds * 10 ** 9)


def body(expected=1, amount=400, eff=None, reason="fix"):
    return {"expected_revision": expected, "amount": amount, "effective_at": eff or past(),
            "reason": reason}


def post(api, token, pid, b, key=None):
    return api.call("POST", f"/payments/{pid}/corrections", token, key or new_key(), b)


# ---------------------------------------------------------------- endpoint basics

def test_R3_COR_10_REV_2_response_shape_and_revision(world, api):
    p = world.pay("ada", "bob", 1000)
    eff = past()
    r = post(api, world.tok["ada"], p["payment_id"], body(eff=eff, reason="corrected amount"))
    assert r.status_code == 201, r.text
    c = r.json()
    assert set(c) == REVISION_KEYS, set(c) ^ REVISION_KEYS
    assert (c["payment_id"], c["revision"], c["amount"], c["reason"]) == \
        (p["payment_id"], 2, 400, "corrected amount")
    assert ns(c["effective_at"]) == ns(eff)
    assert ns(c["recorded_at"]) > ns(p["created_at"])


def test_R3_COR_1_requires_key_400(world, api):
    p = world.pay("ada", "bob", 1000)
    for key in (None, ""):
        r = api.call("POST", f"/payments/{p['payment_id']}/corrections", world.tok["ada"], key,
                     body())
        assert_error(r, 400, "missing_idempotency_key")


def test_R3_COR_2_receiver_and_third_party_403(world, api):
    p = world.pay("ada", "bob", 1000)
    for h in ("bob", "cy", "op"):
        assert_error(post(api, world.tok[h], p["payment_id"], body()), 403, "forbidden")


def test_R3_COR_3_unknown_payment_404(world, api):
    assert_error(post(api, world.tok["ada"], "p_nope", body()), 404, "not_found")


@pytest.mark.parametrize("field", ["expected_revision", "amount", "effective_at", "reason"])
def test_R3_COR_4_each_field_missing_422(world, api, field):
    p = world.pay("ada", "bob", 1000)
    b = body()
    del b[field]
    assert_error(post(api, world.tok["ada"], p["payment_id"], b), 422, "validation_failed")


@pytest.mark.parametrize("value,ok", [(0, False), (-1, False), (1.5, False), ("1", False),
                                      (True, False), (None, False), (1.0, True)])
def test_R3_COR_5_expected_revision_rules(world, api, value, ok):
    p = world.pay("ada", "bob", 1000)
    r = post(api, world.tok["ada"], p["payment_id"], body(expected=value))
    if ok:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 422, "validation_failed")


@pytest.mark.parametrize("value,ok", [(-1, False), (1_000_000_001, False), (2.5, False),
                                      ("5", False), (True, False), (None, False), (0, True),
                                      (1_000_000_000, None)])
def test_R3_COR_6_amount_rules(world, api, value, ok):
    p = world.pay("ada", "bob", 1000)
    r = post(api, world.tok["ada"], p["payment_id"], body(amount=value))
    if ok is None:  # valid value, but ada cannot afford +999999000 now
        assert_error(r, 409, "insufficient_funds")
    elif ok:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 422, "validation_failed")


@pytest.mark.parametrize("reason,ok", [("", False), ("x" * 201, False), (5, False),
                                       (None, False), ("x", True), ("x" * 200, True),
                                       ("🍕" * 200, True), (" ", True)])
def test_R3_COR_7_reason_rules(world, api, reason, ok):
    p = world.pay("ada", "bob", 1000)
    r = post(api, world.tok["ada"], p["payment_id"], body(reason=reason))
    if ok:
        assert r.status_code == 201, r.text
        assert r.json()["reason"] == reason
    else:
        assert_error(r, 422, "validation_failed")


@pytest.mark.parametrize("eff", ["2026-09-20T12:00:00", "2026-09-20", "", "yesterday", 5, None])
def test_R3_COR_8_COR_9_effective_at_invalid_422(world, api, eff):
    p = world.pay("ada", "bob", 1000)
    assert_error(post(api, world.tok["ada"], p["payment_id"], body(eff=eff)), 422,
                 "validation_failed")


def test_R3_COR_8_effective_at_future_422(world, api):
    p = world.pay("ada", "bob", 1000)
    fut = iso_ns(now_ns() + 3 * 10 ** 9)
    assert_error(post(api, world.tok["ada"], p["payment_id"], body(eff=fut)), 422,
                 "validation_failed")
    assert api.me(world.tok["ada"])["balance"] == 9000


def test_R3_COR_9_body_not_object_400(world, api):
    p = world.pay("ada", "bob", 1000)
    r = api.call("POST", f"/payments/{p['payment_id']}/corrections", world.tok["ada"], new_key(),
                 content=b"[1]")
    assert_error(r, 400, "malformed_request")


def test_R3_COR_11_stale_revision_409(world, api):
    p = world.pay("ada", "bob", 1000)
    assert post(api, world.tok["ada"], p["payment_id"], body(expected=1, amount=900)
                ).status_code == 201
    for exp in (1, 3):
        assert_error(post(api, world.tok["ada"], p["payment_id"], body(expected=exp)), 409,
                     "stale_revision")
    assert post(api, world.tok["ada"], p["payment_id"], body(expected=2, amount=800)
                ).status_code == 201


def test_R3_COR_12_COR_13_replay_after_newer_and_reuse(world, api):
    p = world.pay("ada", "bob", 1000)
    key = new_key()
    b1 = body(expected=1, amount=900)
    first = post(api, world.tok["ada"], p["payment_id"], b1, key)
    post(api, world.tok["ada"], p["payment_id"], body(expected=2, amount=800))
    again = post(api, world.tok["ada"], p["payment_id"], b1, key)
    assert again.status_code == 200 and again.json() == first.json()
    assert api.me(world.tok["ada"])["balance"] == 9200
    assert_error(post(api, world.tok["ada"], p["payment_id"], {**b1, "amount": 1}, key), 409,
                 "idempotency_key_reuse")
    assert_error(post(api, world.tok["ada"], p["payment_id"], {**b1, "amount": -1}, key), 409,
                 "idempotency_key_reuse")             # claimed key before validation


def test_R3_COR_14_failed_4xx_key_reusable_and_concurrent_identical(world, api):
    p = world.pay("ada", "bob", 1000)
    key = new_key()
    assert post(api, world.tok["ada"], p["payment_id"], body(expected=7), key).status_code == 409
    assert post(api, world.tok["ada"], p["payment_id"], body(expected=1, amount=990), key
                ).status_code == 201
    q = world.pay("ada", "bob", 1000)
    key2 = new_key()
    b = body(expected=1, amount=500)
    res = run_parallel(lambda _: post(api, world.tok["ada"], q["payment_id"], b, key2), 20)
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and codes.count(200) == 19, codes
    assert len({json.dumps(r.json(), sort_keys=True) for r in res}) == 1


def test_R3_COR_15_precedence_pairs(world, api):
    p = world.pay("ada", "bob", 1000)
    t = world.tok
    assert_error(post(api, t["cy"], "p_nope", body(amount=-1)), 422, "validation_failed")
    assert_error(post(api, t["cy"], "p_nope", body()), 404, "not_found")
    assert_error(post(api, t["bob"], p["payment_id"], body(expected=9)), 403, "forbidden")
    # stale before insufficient
    assert_error(post(api, t["ada"], p["payment_id"], body(expected=9, amount=10 ** 9)), 409,
                 "stale_revision")


def test_R3_COR_16_concurrent_same_expected_one_wins(world, api):
    p = world.pay("ada", "bob", 1000)
    res = run_parallel(lambda i: post(api, world.tok["ada"], p["payment_id"],
                                      body(expected=1, amount=900 - i)), 20)
    codes = [r.status_code for r in res]
    assert codes.count(201) == 1, codes
    assert all(c in (201, 409) for c in codes)
    assert {r.json()["error"]["code"] for r in res if r.status_code == 409} == {"stale_revision"}
    won = next(r.json() for r in res if r.status_code == 201)
    assert api.me(world.tok["ada"])["balance"] == 10000 - won["amount"]
    revs = api.revisions(world.tok["ada"], p["payment_id"]).json()["revisions"]
    assert [x["revision"] for x in revs] == [1, 2]


# ---------------------------------------------------------------- money

def test_R3_MNY_1_MNY_2_delta_moves_between_same_wallets(world, api):
    p = world.pay("ada", "bob", 1000)
    before = {h: api.me(t)["balance"] for h, t in world.tok.items()}
    assert post(api, world.tok["ada"], p["payment_id"], body(amount=1300)).status_code == 201
    mid = {h: api.me(t)["balance"] for h, t in world.tok.items()}
    assert mid["ada"] == before["ada"] - 300 and mid["bob"] == before["bob"] + 300
    assert post(api, world.tok["ada"], p["payment_id"], body(expected=2, amount=200)
                ).status_code == 201
    after = {h: api.me(t)["balance"] for h, t in world.tok.items()}
    assert after["ada"] == mid["ada"] + 1100 and after["bob"] == mid["bob"] - 1100
    for h in ("cy", "dee", "op"):
        assert after[h] == before[h]
    assert sum(after.values()) == world.seeded_total


def test_R3_MNY_3_MNY_9_current_unaffordable_409_before_historical(world, api):
    p = world.pay("cy", "bob", 1500)              # cy now 0
    assert_error(post(api, world.tok["cy"], p["payment_id"], body(amount=1600)), 409,
                 "insufficient_funds")
    q = world.pay("ada", "bob", 1000)
    api.pay(world.tok["bob"], "dee", 3500)        # bob spends; can't give 1000 back now
    assert_error(post(api, world.tok["ada"], q["payment_id"], body(amount=0)), 409,
                 "insufficient_funds")


def test_R3_MNY_3_held_funds_count_as_unavailable(world, api):
    p = world.pay("ada", "bob", 1000)
    api.call("POST", "/authorizations", world.tok["ada"], new_key(),
             {"to_handle": "cy", "amount": 9000})   # ada: total 9000, available 0
    assert_error(post(api, world.tok["ada"], p["payment_id"], body(amount=1001)), 409,
                 "insufficient_funds")


def test_R3_MNY_4_MNY_6_historical_overdraft_and_no_trace(world, api):
    # bob receives 1000, spends it, then receives it back later; a backdated decrease would put
    # bob below zero in between
    p = world.pay("ada", "bob", 1000)
    world.pay("bob", "dee", 3500)                 # bob: 2000+... let the API compute
    world.pay("dee", "bob", 3500)
    eff = iso_ns(ns(p["created_at"]))             # unchanged time, amount 0
    tk = world.tok
    snap_before = api.statement(tk["bob"]).json()
    revs_before = api.revisions(tk["ada"], p["payment_id"]).json()
    bal_before = {h: api.me(t)["balance"] for h, t in tk.items()}
    key = new_key()
    r = post(api, tk["ada"], p["payment_id"], body(amount=0, eff=eff), key)
    assert_error(r, 409, "historical_overdraft")
    assert {h: api.me(t)["balance"] for h, t in tk.items()} == bal_before
    assert api.revisions(tk["ada"], p["payment_id"]).json() == revs_before
    now_st = api.statement(tk["bob"]).json()
    assert now_st["entries"] == snap_before["entries"]
    # the key stays reusable
    assert post(api, tk["ada"], p["payment_id"], body(amount=900, eff=eff), key
                ).status_code in (201, 409)


def test_R3_MNY_5_boundary_combines_same_instant(api, make_world):
    w = make_world()
    tk = w.tok
    # cy (0 after seeds... cy has 1500) sends 1500 and receives 1500 in one settlement instant
    st = api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "cy", "to_handle": "dee", "amount": 1500},
        {"from_handle": "ada", "to_handle": "cy", "amount": 1500}]}).json()
    assert len(st["payments"]) == 2
    p = w.pay("ada", "cy", 100)
    # backdate the 100 to exactly the settlement instant: cy's boundary combines -1500 +1500 +100
    r = post(api, tk["ada"], p["payment_id"], body(amount=100, eff=st["committed_at"]))
    assert r.status_code == 201, r.text


def test_R3_MNY_8_overdraft_on_available_via_hold(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)              # bob 3500
    a = api.call("POST", "/authorizations", tk["bob"], new_key(),
                 {"to_handle": "dee", "amount": 3000}).json()   # bob available 500
    api.call("POST", f"/authorizations/{a['authorization_id']}/void", tk["bob"])
    # backdating a decrease (bob gives back 900) to while the hold was open: bob's available
    # at that time was 500 → negative
    eff = iso_ns(ns(a["created_at"]) + US)
    r = post(api, tk["ada"], p["payment_id"], body(amount=100, eff=eff))
    assert_error(r, 409, "historical_overdraft")


def test_R3_MNY_10_KN_9_zero_reverses(world, api):
    p = world.pay("ada", "bob", 1000)
    r = post(api, world.tok["ada"], p["payment_id"], body(amount=0, eff=p["created_at"]))
    assert r.status_code == 201, r.text
    assert api.me(world.tok["ada"])["balance"] == 10000
    assert api.me(world.tok["bob"])["balance"] == 2500
    e = next(e for e in api.statement(world.tok["ada"]).json()["entries"]
             if e["payment"]["payment_id"] == p["payment_id"])
    assert e["delta"] == 0 and e["payment"]["amount"] == 0 and e["revision"] == 2


def test_R3_MNY_11_same_amount_moves_only_history(world, api):
    p = world.pay("ada", "bob", 1000)
    eff = iso_ns(ns(world.fx["payments"][0]["created_at"]) + US)
    r = post(api, world.tok["ada"], p["payment_id"], body(amount=1000, eff=eff))
    assert r.status_code == 201, r.text
    assert api.me(world.tok["ada"])["balance"] == 9000
    assert api.me(world.tok["ada"], as_of=eff)["balance"] == 12000 - 500 - 1000


def test_R3_MNY_12_correct_request_pay_and_seeded(world, api):
    tk = world.tok
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 600}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    assert post(api, tk["ada"], rp["payment_id"], body(amount=500)).status_code == 201
    req = api.call("GET", "/requests", tk["ada"]).json()["requests"][0]
    assert req["status"] == "paid" and req["payment_id"] == rp["payment_id"]
    assert req["amount"] == 600
    assert post(api, tk["ada"], "p_s1", body(amount=400)).status_code == 201
    # seeded correction never changes the opening balance (R3-REV.5)
    assert api.me(tk["ada"], as_of="1970-01-01T00:00:00Z")["balance"] == 12000


def test_R3_REV_5_REV_7_REV_8_openings_immutable_recorded_increasing(world, api):
    p = world.pay("ada", "bob", 1000)
    recs = []
    for i, amt in enumerate((900, 800, 700), start=1):
        r = post(api, world.tok["ada"], p["payment_id"], body(expected=i, amount=amt))
        assert r.status_code == 201
        recs.append(ns(r.json()["recorded_at"]))
    assert recs == sorted(recs) and len(set(recs)) == 3
    revs = api.revisions(world.tok["bob"], p["payment_id"]).json()["revisions"]
    assert [x["revision"] for x in revs] == [1, 2, 3, 4]
    assert [x["amount"] for x in revs] == [1000, 900, 800, 700]
    assert revs[0]["reason"] == "" and ns(revs[0]["recorded_at"]) == ns(p["created_at"])
    for a, b in zip(revs, revs[1:]):
        assert ns(b["recorded_at"]) > ns(a["recorded_at"])
    assert api.me(world.tok["ada"], as_of="1970-01-01T00:00:00Z")["balance"] == 12000
    assert api.me(world.tok["bob"], as_of="1970-01-01T00:00:00Z")["balance"] == 2000


def test_R3_REV_9_parties_visibility_unchanged(world, api):
    p = world.pay("ada", "bob", 1000, visibility="private")
    post(api, world.tok["ada"], p["payment_id"], body(amount=500))
    assert all(x["payment_id"] != p["payment_id"]
               for x in api.call("GET", "/activity", world.tok["cy"]).json()["payments"])
    e = next(e for e in api.statement(world.tok["bob"]).json()["entries"]
             if e["payment"]["payment_id"] == p["payment_id"])
    assert (e["payment"]["from_user_id"], e["payment"]["to_user_id"],
            e["payment"]["visibility"]) == ("u_ada", "u_bob", "private")


# ---------------------------------------------------------------- revisions endpoint

def test_R3_RVL_1_RVL_5_list_shape(world, api):
    p = world.pay("ada", "bob", 1000)
    c = post(api, world.tok["ada"], p["payment_id"], body()).json()
    r = api.revisions(world.tok["ada"], p["payment_id"])
    assert r.status_code == 200 and set(r.json()) == {"revisions"}
    revs = r.json()["revisions"]
    for x in revs:
        assert set(x) == REVISION_KEYS
    assert revs[1] == c


def test_R3_RVL_2_RVL_3_RVL_4_access(world, api):
    p = world.pay("ada", "bob", 1000)                # public
    for h in ("cy", "op"):
        assert_error(api.revisions(world.tok[h], p["payment_id"]), 404, "not_found")
    assert api.revisions(world.tok["bob"], p["payment_id"]).status_code == 200
    assert_error(api.call("GET", f"/payments/{p['payment_id']}/revisions"), 401,
                 "unauthenticated")
    assert_error(api.revisions(world.tok["ada"], "p_nope"), 404, "not_found")


# ---------------------------------------------------------------- linked payments

def test_R3_SET_1_SET_2_SET_3_member_revision_and_immutable(world, api):
    tk = world.tok
    key = new_key()
    b = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}
    st = api.call("POST", "/settlements", tk["op"], key, b).json()
    m = st["payments"][0]
    revs = api.revisions(tk["ada"], m["payment_id"]).json()["revisions"]
    assert ns(revs[0]["effective_at"]) == ns(revs[0]["recorded_at"]) == ns(st["committed_at"])
    assert_error(post(api, tk["ada"], m["payment_id"], body(amount=5)), 422,
                 "linked_payment_immutable")
    again = api.call("POST", "/settlements", tk["op"], key, b)
    assert again.status_code == 200 and again.json() == st


def test_R3_SET_4_capture_correction_422_linked(world, api):
    tk = world.tok
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "bob", "amount": 100}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                   new_key(), {}).json()
    assert_error(post(api, tk["ada"], cap["payment_id"], body(amount=50)), 422,
                 "linked_payment_immutable")
    revs = api.revisions(tk["bob"], cap["payment_id"]).json()["revisions"]
    assert ns(revs[0]["effective_at"]) == ns(cap["created_at"])


def test_R3_SET_6_holds_not_in_statement(world, api):
    tk = world.tok
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "bob", "amount": 100}).json()
    api.call("POST", f"/authorizations/{a['authorization_id']}/void", tk["ada"])
    entries = api.statement(tk["ada"]).json()["entries"]
    assert [e["payment"]["payment_id"] for e in entries] == ["p_s1", "p_s2"]
