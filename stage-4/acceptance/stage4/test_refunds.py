"""Refunds and single corrections under stage 4. Ledger R4-PATH (refunds), R4-REF, R4-RSH, R4-RCOR."""
import json

import pytest

from s4lib import (PAYMENT_KEYS, REVISION_KEYS, assert_error, iso_ns, new_key, ns, now_ns,
                   refund, run_parallel)


def past(s=5):
    return iso_ns(now_ns() - s * 10 ** 9)


def correct(api, tok, pid, expected, amount, eff=None, key=None):
    return api.correct(tok, pid, expected, amount, eff or past(), key=key)


# ---------------------------------------------------------------- endpoint

def test_R4_REF_1_RSH_1_RSH_2_receiver_refunds_201(world, api):
    p = world.pay("ada", "bob", 1000, note="dinner", visibility="private")
    r = refund(api, world.tok["bob"], p["payment_id"], 200)
    assert r.status_code == 201, r.text
    f = r.json()
    assert set(f) == PAYMENT_KEYS, set(f) ^ PAYMENT_KEYS
    assert (f["from_user_id"], f["to_user_id"], f["amount"]) == ("u_bob", "u_ada", 200)
    assert (f["refund_of"], f["request_id"], f["authorization_id"], f["settlement_id"]) == \
        (p["payment_id"], None, None, None)
    assert (f["note"], f["visibility"]) == ("dinner", "private")
    assert f["payment_id"] != p["payment_id"]
    assert api.me(world.tok["ada"])["balance"] == 9200
    assert api.me(world.tok["bob"])["balance"] == 3300


def test_R4_REF_2_sender_third_party_operator_403(world, api):
    p = world.pay("ada", "bob", 1000)
    for h in ("ada", "cy", "op"):
        assert_error(refund(api, world.tok[h], p["payment_id"], 10), 403, "forbidden")


def test_R4_REF_3_unknown_404(world, api):
    assert_error(refund(api, world.tok["bob"], "p_nope", 10), 404, "not_found")


def test_R4_REF_4_targets_direct_request_capture(world, api):
    tk = world.tok
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 300}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    r = refund(api, tk["bob"], rp["payment_id"], 100)
    assert r.status_code == 201 and r.json()["request_id"] is None
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "dee", "amount": 500}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["dee"],
                   new_key(), {"amount": 400}).json()
    r = refund(api, tk["dee"], cap["payment_id"], 400)
    assert r.status_code == 201 and r.json()["authorization_id"] is None
    assert r.json()["refund_of"] == cap["payment_id"]


def test_R4_REF_5_refund_of_refund_422(world, api):
    p = world.pay("ada", "bob", 1000)
    f = refund(api, world.tok["bob"], p["payment_id"], 100).json()
    assert_error(refund(api, world.tok["ada"], f["payment_id"], 10), 422, "invalid_refund_target")


@pytest.mark.parametrize("amount,ok", [(0, False), (-1, False), (1_000_000_001, False),
                                       (2.5, False), ("5", False), (True, False), (None, False),
                                       (1, True)])
def test_R4_REF_6_amount_rules(world, api, amount, ok):
    p = world.pay("ada", "bob", 1000)
    r = refund(api, world.tok["bob"], p["payment_id"], amount)
    if ok:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 422, "validation_failed")


def test_R4_REF_6_missing_amount_and_float_forms(world, api):
    p = world.pay("ada", "bob", 1000)
    r = api.call("POST", f"/payments/{p['payment_id']}/refunds", world.tok["bob"], new_key(), {})
    assert_error(r, 422, "validation_failed")
    r = api.call("POST", f"/payments/{p['payment_id']}/refunds", world.tok["bob"], new_key(),
                 content=b'{"amount": 1e2}')
    assert r.status_code == 201 and r.json()["amount"] == 100


def test_R4_REF_7_cumulative_cap_uses_corrected_amount(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    assert refund(api, tk["bob"], p["payment_id"], 600).status_code == 201
    assert_error(refund(api, tk["bob"], p["payment_id"], 401), 422, "refund_exceeds_payment")
    assert correct(api, tk["ada"], p["payment_id"], 1, 800).status_code == 201
    assert_error(refund(api, tk["bob"], p["payment_id"], 201), 422, "refund_exceeds_payment")
    assert refund(api, tk["bob"], p["payment_id"], 200).status_code == 201   # exactly 800 now
    assert correct(api, tk["ada"], p["payment_id"], 2, 900).status_code == 201
    assert refund(api, tk["bob"], p["payment_id"], 100).status_code == 201
    assert_error(refund(api, tk["bob"], p["payment_id"], 1), 422, "refund_exceeds_payment")


def test_R4_REF_8_available_not_total_atomic(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)                         # bob 3500
    api.call("POST", "/authorizations", tk["bob"], new_key(), {"to_handle": "dee", "amount": 3000})
    before = {h: api.me(t) for h, t in tk.items()}
    assert_error(refund(api, tk["bob"], p["payment_id"], 600), 409, "insufficient_funds")
    assert {h: api.me(t) for h, t in tk.items()} == before
    assert refund(api, tk["bob"], p["payment_id"], 500).status_code == 201


def test_R4_REF_9_precedence_pairs(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    f = refund(api, tk["bob"], p["payment_id"], 100).json()
    assert_error(refund(api, tk["cy"], "p_nope", 0), 422, "validation_failed")   # 422 < 404
    assert_error(refund(api, tk["cy"], "p_nope", 5), 404, "not_found")           # 404 < 403
    assert_error(refund(api, tk["bob"], f["payment_id"], 5), 403, "forbidden")    # 403 < target
    assert_error(refund(api, tk["ada"], f["payment_id"], 10 ** 9), 422,
                 "invalid_refund_target")                                         # target < cap
    api.pay(tk["bob"], "dee", 3400)                                               # bob: 0 avail.
    assert_error(refund(api, tk["bob"], p["payment_id"], 901), 422,
                 "refund_exceeds_payment")                                        # cap < funds
    assert_error(refund(api, tk["bob"], p["payment_id"], 900), 409, "insufficient_funds")


def test_R4_PATH_1_refund_idempotency(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    path = f"/payments/{p['payment_id']}/refunds"
    for key in (None, ""):
        assert_error(api.call("POST", path, tk["bob"], key, {"amount": 5}), 400,
                     "missing_idempotency_key")
    assert_error(api.call("POST", path, tk["bob"], "k" * 256, {"amount": 5}), 422,
                 "validation_failed")
    key = new_key()
    first = api.call("POST", path, tk["bob"], key, {"amount": 5})
    assert first.status_code == 201
    assert_error(api.call("POST", path, tk["bob"], key, {"amount": 6}), 409,
                 "idempotency_key_reuse")
    assert_error(api.call("POST", path, tk["bob"], key, {"amount": -1}), 409,
                 "idempotency_key_reuse")
    k2 = new_key()
    assert api.call("POST", path, tk["bob"], k2, {"amount": 10 ** 6}).status_code == 422
    assert api.call("POST", path, tk["bob"], k2, {"amount": 7}).status_code == 201
    k3 = new_key()
    res = run_parallel(lambda _: api.call("POST", path, tk["bob"], k3, {"amount": 9}), 20)
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and codes.count(200) == 19, codes
    assert len({json.dumps(r.json(), sort_keys=True) for r in res}) == 1
    assert api.me(tk["bob"])["balance"] == 3500 - 5 - 7 - 9


def test_R4_RSH_3_replay_200_original_even_after_more_refunds(world, api):
    p = world.pay("ada", "bob", 1000)
    key = new_key()
    first = refund(api, world.tok["bob"], p["payment_id"], 100, key=key)
    refund(api, world.tok["bob"], p["payment_id"], 100)
    again = refund(api, world.tok["bob"], p["payment_id"], 100, key=key)
    assert again.status_code == 200 and again.json() == first.json()
    assert api.me(world.tok["bob"])["balance"] == 3300


def test_R4_RSH_4_no_reopen(world, api):
    tk = world.tok
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 300}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    refund(api, tk["bob"], rp["payment_id"], 300)
    q = api.call("GET", "/requests", tk["ada"]).json()["requests"][0]
    assert (q["status"], q["payment_id"]) == ("paid", rp["payment_id"])
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "dee", "amount": 500}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["dee"],
                   new_key(), {"amount": 200}).json()
    held_before = api.me(tk["ada"])["held"]
    refund(api, tk["dee"], cap["payment_id"], 200)
    got = next(x for x in api.call("GET", "/authorizations", tk["ada"]).json()["authorizations"]
               if x["authorization_id"] == a["authorization_id"])
    assert (got["status"], got["captured_amount"], got["remaining_amount"]) == ("captured", 200, 0)
    assert api.me(tk["ada"])["held"] == held_before == 0


def test_R4_RSH_5_refund_of_null_on_every_payment_surface(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 10)
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 5}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    st = api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "dee", "to_handle": "cy", "amount": 3}]}).json()
    for obj in (p, rp, st["payments"][0]):
        assert set(obj) == PAYMENT_KEYS and obj["refund_of"] is None
    for x in api.call("GET", "/activity", tk["ada"], params={"limit": 200}).json()["payments"]:
        assert set(x) == PAYMENT_KEYS and x["refund_of"] is None
    for e in api.statement(tk["ada"]).json()["entries"]:
        assert e["payment"]["refund_of"] is None


def test_R4_RSH_6_refund_in_feed_statement_and_history(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)                       # public
    f = refund(api, tk["bob"], p["payment_id"], 250).json()
    feed_cy = [x["payment_id"] for x in api.call("GET", "/activity", tk["cy"]).json()["payments"]]
    assert f["payment_id"] in feed_cy
    st = api.statement(tk["ada"]).json()
    e = next(e for e in st["entries"] if e["payment"]["payment_id"] == f["payment_id"])
    assert e["delta"] == 250 and e["revision"] == 1
    revs = api.revisions(tk["ada"], f["payment_id"]).json()["revisions"]
    assert len(revs) == 1 and ns(revs[0]["effective_at"]) == ns(f["created_at"])
    assert revs[0]["correction_batch_id"] is None
    t = ns(f["created_at"])
    assert api.me(tk["ada"], as_of=iso_ns(t))["balance"] == 9250
    assert api.me(tk["ada"], as_of=iso_ns(t - 1000))["balance"] == 9000


def test_R4_RSH_7_refund_and_capture_not_correctable(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    f = refund(api, tk["bob"], p["payment_id"], 100).json()
    assert_error(correct(api, tk["bob"], f["payment_id"], 1, 50), 422, "linked_payment_immutable")
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "dee", "amount": 500}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["dee"],
                   new_key(), {}).json()
    assert_error(correct(api, tk["ada"], cap["payment_id"], 1, 50), 422, "linked_payment_immutable")


# ---------------------------------------------------------------- single corrections

def test_R4_RCOR_1_single_correction_still_works(world, api):
    p = world.pay("ada", "bob", 1000)
    r = correct(api, world.tok["ada"], p["payment_id"], 1, 700)
    assert r.status_code == 201, r.text
    assert set(r.json()) == REVISION_KEYS and r.json()["correction_batch_id"] is None


def test_R4_RCOR_2_floor_at_refunded(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    refund(api, tk["bob"], p["payment_id"], 300)
    assert_error(correct(api, tk["ada"], p["payment_id"], 1, 299), 422, "refund_exceeds_payment")
    assert correct(api, tk["ada"], p["payment_id"], 1, 300).status_code == 201


def test_R4_RCOR_3_available_not_total(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    api.call("POST", "/authorizations", tk["ada"], new_key(), {"to_handle": "cy", "amount": 9000})
    assert_error(correct(api, tk["ada"], p["payment_id"], 1, 1001), 409, "insufficient_funds")


def test_R4_RCOR_4_precedence_stale_before_refund_exceeds(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    refund(api, tk["bob"], p["payment_id"], 500)
    assert_error(correct(api, tk["ada"], p["payment_id"], 2, 10), 409, "stale_revision")
    api.pay(tk["bob"], "dee", 3000)                        # bob can't give back much now
    assert_error(correct(api, tk["ada"], p["payment_id"], 1, 10), 422, "refund_exceeds_payment")


def test_R4_RCOR_5_member_single_correction_still_422(world, api):
    st = api.call("POST", "/settlements", world.tok["op"], new_key(), {"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100}]}).json()
    m = st["payments"][0]
    assert_error(correct(api, world.tok["ada"], m["payment_id"], 1, 50), 422,
                 "linked_payment_immutable")
