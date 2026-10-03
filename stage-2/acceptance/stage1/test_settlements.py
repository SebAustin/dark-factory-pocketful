"""§11 atomic net settlements. Ledger R-1.3, R-11.x."""
import pytest

from conftest import (PAYMENT_KEYS, RFC3339, assert_error, base_fixture, new_key, run_parallel,
                      user)


def op_fixture(**over):
    fx = base_fixture(users=[
        user("u_ada", "ada", 10000), user("u_bob", "bob", 0), user("u_cy", "cy", 0),
        user("u_dee", "dee", 5000), user("u_op", "op", 0),
    ], settlement_operator_ids=["u_op"])
    fx.update(over)
    return fx


@pytest.fixture
def ow(make_world):
    return make_world(op_fixture())


def settle(api, w, transfers, key=None, token=None):
    return api.post("/settlements", token or w.tok["op"], key or new_key(),
                    {"transfers": transfers})


def t(frm, to, amount, **f):
    return {"from_handle": frm, "to_handle": to, "amount": amount, **f}


def test_R11_15_R1_3_operator_settlement_201(ow, api):
    r = settle(api, ow, [t("ada", "bob", 100), t("dee", "cy", 50, note="x",
                                                   visibility="private")])
    assert r.status_code == 201, r.text
    s = r.json()
    assert set(s) >= {"settlement_id", "committed_at", "payments"}
    assert isinstance(s["settlement_id"], str) and len(s["settlement_id"]) <= 64
    assert RFC3339.match(s["committed_at"])
    ps = s["payments"]
    assert [(p["from_handle"], p["to_handle"], p["amount"]) for p in ps] == \
        [("ada", "bob", 100), ("dee", "cy", 50)]
    for p in ps:
        assert set(p) == PAYMENT_KEYS
    assert ow.balances() == {"ada": 9900, "bob": 100, "cy": 50, "dee": 4950, "op": 0}


def test_R11_17_members_share_created_at_equal_committed_at(ow, api):
    s = settle(api, ow, [t("ada", "bob", 1), t("ada", "cy", 1), t("dee", "bob", 1)]).json()
    for p in s["payments"]:
        assert p["created_at"] == s["committed_at"]
        assert p["request_id"] is None
        assert p["settlement_id"] == s["settlement_id"]


def test_R11_16_member_settlement_id_and_nonmember_null(ow, api):
    s = settle(api, ow, [t("ada", "bob", 5)]).json()
    direct = api.pay(ow.tok["ada"], "bob", 5).json()
    assert direct["settlement_id"] is None
    rid = api.request(ow.tok["bob"], "ada", 5).json()["request_id"]
    via_req = api.pay_request(ow.tok["ada"], rid).json()
    assert via_req["settlement_id"] is None
    feed = {p["payment_id"]: p for p in api.feed(ow.tok["cy"])["payments"]}
    assert feed[s["payments"][0]["payment_id"]]["settlement_id"] == s["settlement_id"]
    assert feed[direct["payment_id"]]["settlement_id"] is None
    assert feed[via_req["payment_id"]]["settlement_id"] is None


def test_R11_4_no_token_401(ow, api):
    r = api.post("/settlements", None, new_key(), {"transfers": [t("ada", "bob", 1)]})
    assert_error(r, 401, "unauthenticated")


def test_R11_4_R11_1_non_operator_403(ow, api):
    r = settle(api, ow, [t("ada", "bob", 1)], token=ow.tok["ada"])
    assert_error(r, 403, "forbidden")
    assert ow.balances()["ada"] == 10000


def test_R11_1_default_no_operators_403(make_world, api):
    fx = op_fixture()
    del fx["settlement_operator_ids"]
    w = make_world(fx)
    assert_error(settle(api, w, [t("ada", "bob", 1)]), 403, "forbidden")


def test_R11_22_non_operator_403_even_with_bad_body(ow, api):
    r = api.post("/settlements", ow.tok["ada"], new_key(), {"transfers": []})
    assert_error(r, 403, "forbidden")


def test_R11_2_operator_settles_between_third_parties(ow, api):
    r = settle(api, ow, [t("dee", "ada", 300)])
    assert r.status_code == 201
    assert ow.balances()["dee"] == 4700 and ow.balances()["op"] == 0


def test_R11_6_transfer_count_bounds(ow, api):
    assert_error(settle(api, ow, []), 422, "validation_failed")
    assert_error(settle(api, ow, [t("ada", "bob", 1)] * 33), 422, "validation_failed")
    assert ow.balances()["ada"] == 10000
    r = settle(api, ow, [t("ada", "bob", 1)] * 32)
    assert r.status_code == 201 and len(r.json()["payments"]) == 32
    assert settle(api, ow, [t("ada", "bob", 1)]).status_code == 201


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": 1_000_000_001}, {"amount": "5"}, {"amount": True},
    {"amount": 2.5}, {"amount": None}, {"note": "n" * 201}, {"note": None},
    {"visibility": "x"}, {"visibility": None},
])
def test_R11_7_entry_amount_note_visibility_rules(ow, api, bad):
    entry = {**t("ada", "bob", 10), **bad}
    assert_error(settle(api, ow, [entry]), 422, "validation_failed")
    assert ow.balances()["ada"] == 10000


def test_R11_7_entry_defaults_and_float_amount(ow, api):
    r = api.call("POST", "/settlements", ow.tok["op"], new_key(),
                 content=b'{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1e3}]}')
    assert r.status_code == 201, r.text
    p = r.json()["payments"][0]
    assert (p["amount"], p["note"], p["visibility"]) == (1000, "", "public")


def test_R11_8_unknown_handle_404(ow, api):
    assert_error(settle(api, ow, [t("ada", "nobody", 1)]), 404, "not_found")
    assert_error(settle(api, ow, [t("nobody", "ada", 1)]), 404, "not_found")


def test_R11_8_self_transfer_422(ow, api):
    assert_error(settle(api, ow, [t("ada", "ada", 1)]), 422, "self_payment")


@pytest.mark.parametrize("body", [{}, {"transfers": "x"}, {"transfers": {"a": 1}},
                                  {"transfers": [5]}, {"transfers": [[]]},
                                  {"transfers": None}])
def test_R11_8_malformed_shape_422(ow, api, body):
    r = api.post("/settlements", ow.tok["op"], new_key(), body)
    assert_error(r, 422, "validation_failed")


def test_R11_8_entry_handle_wrong_type(ow, api):
    r = settle(api, ow, [{"from_handle": 5, "to_handle": "bob", "amount": 1}])
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})


def test_R11_9_entry_error_order(ow, api):
    assert_error(settle(api, ow, [t("ada", "ada", 1), t("ada", "nobody", 1)]), 422,
                 "self_payment")
    assert_error(settle(api, ow, [t("ada", "nobody", 1), t("ada", "ada", 1)]), 404, "not_found")
    # unaffordable first entry + invalid second entry: entry error wins over funds
    assert_error(settle(api, ow, [t("bob", "ada", 999), t("ada", "cy", 0)]), 422,
                 "validation_failed")
    assert_error(settle(api, ow, [t("bob", "ada", 999), t("ada", "nobody", 1)]), 404,
                 "not_found")
    assert_error(settle(api, ow, [t("ada", "cy", 0), t("ada", "nobody", 1)]), 422,
                 "validation_failed")


def test_R11_11_net_affordability_chain(ow, api):
    # bob holds 0: receives 100 then forwards 100 -> net 0, affordable in either order
    r = settle(api, ow, [t("bob", "cy", 100), t("ada", "bob", 100)])
    assert r.status_code == 201, r.text
    assert ow.balances()["bob"] == 0 and ow.balances()["cy"] == 100
    r = settle(api, ow, [t("ada", "bob", 100), t("bob", "cy", 100)])
    assert r.status_code == 201


def test_R11_23_repeated_wallet_netting(ow, api):
    r = settle(api, ow, [t("cy", "bob", 50), t("ada", "cy", 30), t("ada", "cy", 20),
                         t("bob", "dee", 50)])
    assert r.status_code == 201, r.text
    assert ow.balances() == {"ada": 9950, "bob": 0, "cy": 0, "dee": 5050, "op": 0}


def test_R11_12_R11_13_collective_shortfall_409_nothing_moves(ow, api):
    feeds = {h: api.feed(tok)["payments"] for h, tok in ow.tok.items()}
    r = settle(api, ow, [t("ada", "bob", 100), t("bob", "cy", 101)])
    assert_error(r, 409, "insufficient_funds")
    assert ow.balances() == {"ada": 10000, "bob": 0, "cy": 0, "dee": 5000, "op": 0}
    assert {h: api.feed(tok)["payments"] for h, tok in ow.tok.items()} == feeds


def test_R11_14_failed_settlement_key_reusable(ow, api):
    key = new_key()
    assert settle(api, ow, [t("ada", "bob", 0)], key=key).status_code == 422
    assert settle(api, ow, [t("bob", "ada", 5)], key=key).status_code == 409
    r = settle(api, ow, [t("ada", "bob", 5)], key=key)
    assert r.status_code == 201
    again = settle(api, ow, [t("ada", "bob", 5)], key=key)
    assert again.status_code == 200 and again.json() == r.json()
    assert ow.balances()["bob"] == 5


def test_R11_18_members_in_feed_by_contract(ow, api):
    s = settle(api, ow, [t("ada", "bob", 1, visibility="public"),
                         t("ada", "bob", 2, visibility="private")]).json()
    pub, priv = (p["payment_id"] for p in s["payments"])
    assert {p["payment_id"] for p in api.feed(ow.tok["dee"])["payments"]} == {pub}
    assert {p["payment_id"] for p in api.feed(ow.tok["bob"])["payments"]} == {pub, priv}


def test_R11_19_response_includes_private_members(ow, api):
    s = settle(api, ow, [t("ada", "bob", 2, visibility="private")]).json()
    assert len(s["payments"]) == 1 and s["payments"][0]["visibility"] == "private"


def test_R11_3_operator_cannot_see_others_private_or_requests(ow, api):
    s = settle(api, ow, [t("ada", "bob", 2, visibility="private")]).json()
    api.pay(ow.tok["ada"], "dee", 3, visibility="private")
    rid = api.request(ow.tok["bob"], "ada", 5).json()["request_id"]
    assert api.feed(ow.tok["op"])["payments"] == []
    assert api.requests_list(ow.tok["op"])["requests"] == []
    assert_error(api.pay_request(ow.tok["op"], rid), {403, 404}, {"forbidden", "not_found"})
    assert_error(api.post(f"/requests/{rid}/cancel", ow.tok["op"]), {403, 404},
                 {"forbidden", "not_found"})
    assert_error(api.post(f"/requests/{rid}/decline", ow.tok["op"]), {403, 404},
                 {"forbidden", "not_found"})
    assert s["payments"][0]["payment_id"]


def test_R3_10_R11_10_unknown_fields_ignored(ow, api):
    r = api.post("/settlements", ow.tok["op"], new_key(), {
        "transfers": [{**t("ada", "bob", 4), "colour": "red"}], "memo": "x"})
    assert r.status_code == 201


def test_R1_6_sum_conserved_after_settlement(ow, api):
    settle(api, ow, [t("ada", "bob", 500), t("bob", "cy", 200), t("dee", "ada", 1)])
    ow.assert_invariants()


def test_R11_13_concurrent_settlements_and_payments_sum_conserved(ow, api):
    def work(i):
        if i % 3 == 0:
            return settle(api, ow, [t("ada", "bob", 400), t("bob", "cy", 400)]).status_code
        if i % 3 == 1:
            return api.pay(ow.tok["ada"], "dee", 400).status_code
        return api.pay(ow.tok["dee"], "bob", 300).status_code

    codes = run_parallel(work, 60, workers=30)
    assert all(c in (201, 409) for c in codes), codes
    ow.assert_invariants()
