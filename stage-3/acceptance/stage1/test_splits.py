"""§8 POST /splits and §9 money and rounding. Ledger R-8.49-8.60, R-9.x, R-4.21."""
import pytest

from conftest import REQUEST_KEYS, RFC3339, assert_error, base_fixture, new_key, user


def split(api, token, amount, handles, key=None, **fields):
    return api.post("/splits", token, key or new_key(),
                    {"amount": amount, "participant_handles": handles, **fields})


def many_world(make_world, n=7):
    users = [user("u_ada", "ada", 0)] + [user(f"u_p{i}", f"p{i}", 0) for i in range(1, n + 1)]
    return make_world(base_fixture(users=users))


def test_R8_49_R8_52_R8_53_R1_1_split_example_3000_3(world, api):
    r = split(api, world.tok["ada"], 3000, ["ada", "bob", "cy"], note="dinner")
    assert r.status_code == 201
    s = r.json()
    assert set(s) >= {"split_id", "amount", "currency", "note", "shares", "requests",
                      "created_at"}
    assert (s["amount"], s["currency"], s["note"]) == (3000, "EUR", "dinner")
    assert s["shares"] == [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                           {"handle": "cy", "amount": 1000}]
    assert RFC3339.match(s["created_at"])
    reqs = s["requests"]
    assert [q["payer_handle"] for q in reqs] == ["bob", "cy"]
    for q in reqs:
        assert set(q) == REQUEST_KEYS
        assert (q["requester_handle"], q["requester_id"]) == ("ada", "u_ada")
        assert (q["amount"], q["status"], q["note"], q["payment_id"]) == (1000, "pending",
                                                                           "dinner", None)
    # the requests are real: visible to their payers
    assert [q["request_id"] for q in api.requests_list(world.tok["bob"])["requests"]] == \
        [reqs[0]["request_id"]]


@pytest.mark.parametrize("amount,n,expected", [
    (1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
    (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1]),
])
def test_R9_2_to_R9_7_R8_51_shares_table_rows(make_world, api, amount, n, expected):
    w = many_world(make_world)
    handles = ["ada"] + [f"p{i}" for i in range(1, n)]
    s = split(api, w.tok["ada"], amount, handles).json()
    assert [x["amount"] for x in s["shares"]] == expected
    assert [x["handle"] for x in s["shares"]] == handles
    assert [q["amount"] for q in s["requests"]] == expected[1:]


def test_R9_1_share_properties_many_amounts(make_world, api):
    w = many_world(make_world)
    for n in range(1, 8):
        handles = [f"p{i}" for i in range(1, n + 1)]
        for amount in (1, 2, 7, 13, 50, 101, 1_000_000_000):
            s = split(api, w.tok["ada"], amount, handles).json()
            shares = [x["amount"] for x in s["shares"]]
            assert sum(shares) == amount
            assert max(shares) - min(shares) <= 1
            assert shares == sorted(shares, reverse=True)
            assert all(isinstance(x, int) for x in shares)


def test_R9_8_order_moves_extra_unit(world, api):
    a = split(api, world.tok["ada"], 10, ["bob", "cy", "dee"]).json()["shares"]
    b = split(api, world.tok["ada"], 10, ["dee", "cy", "bob"]).json()["shares"]
    assert a == [{"handle": "bob", "amount": 4}, {"handle": "cy", "amount": 3},
                 {"handle": "dee", "amount": 3}]
    assert b == [{"handle": "dee", "amount": 4}, {"handle": "cy", "amount": 3},
                 {"handle": "bob", "amount": 3}]


def test_R9_10_no_carry_between_splits(world, api):
    for _ in range(3):
        s = split(api, world.tok["ada"], 1, ["bob", "cy", "dee"]).json()
        assert [x["amount"] for x in s["shares"]] == [1, 0, 0]


def test_R9_9_zero_share_creates_request(world, api):
    s = split(api, world.tok["ada"], 1, ["ada", "bob", "cy"]).json()
    assert [(q["payer_handle"], q["amount"], q["status"]) for q in s["requests"]] == \
        [("bob", 0, "pending"), ("cy", 0, "pending")]
    got = api.requests_list(world.tok["cy"])["requests"]
    assert len(got) == 1 and got[0]["amount"] == 0
    r = api.pay_request(world.tok["cy"], got[0]["request_id"])
    assert r.status_code == 201
    assert r.json()["amount"] == 0
    world.assert_invariants()


def test_R8_50_caller_omitted_all_listed_get_requests(world, api):
    s = split(api, world.tok["ada"], 3000, ["bob", "cy"]).json()
    assert s["shares"] == [{"handle": "bob", "amount": 1500}, {"handle": "cy", "amount": 1500}]
    assert [(q["payer_handle"], q["amount"]) for q in s["requests"]] == [("bob", 1500),
                                                                          ("cy", 1500)]


def test_R8_54_shares_and_requests_order(world, api):
    s = split(api, world.tok["ada"], 100, ["dee", "ada", "bob"]).json()
    assert [x["handle"] for x in s["shares"]] == ["dee", "ada", "bob"]
    assert [x["amount"] for x in s["shares"]] == [34, 33, 33]
    assert sum(x["amount"] for x in s["shares"]) == 100
    assert [q["payer_handle"] for q in s["requests"]] == ["dee", "bob"]
    assert [q["amount"] for q in s["requests"]] == [34, 33]


def test_R8_59_only_caller_valid_zero_requests(world, api):
    r = split(api, world.tok["ada"], 500, ["ada"])
    assert r.status_code == 201
    s = r.json()
    assert s["shares"] == [{"handle": "ada", "amount": 500}]
    assert s["requests"] == []
    assert api.requests_list(world.tok["ada"])["requests"] == []


def test_R8_60_split_ignores_balances(world, api):
    r = split(api, world.tok["cy"], 1_000_000_000, ["cy", "bob", "ada"])
    assert r.status_code == 201
    assert api.balance(world.tok["cy"]) == 0
    world.assert_invariants()


def test_R8_55_split_amount_bounds(world, api):
    t = world.tok["ada"]
    for bad in (0, -1, 1_000_000_001, 2.5, True, "30", None):
        assert_error(split(api, t, bad, ["ada", "bob"]), 422, "validation_failed")
    assert split(api, t, 1_000_000_000, ["ada", "bob"]).status_code == 201
    r = api.call("POST", "/splits", t, new_key(),
                 content=b'{"amount": 3e3, "participant_handles": ["ada","bob","cy"]}')
    assert r.status_code == 201 and r.json()["amount"] == 3000


def test_R8_56_participants_empty_or_duplicate_422(world, api):
    t = world.tok["ada"]
    for handles in ([], ["bob", "bob"], ["ada", "bob", "ada"]):
        assert_error(split(api, t, 30, handles), 422, "validation_failed")
    assert api.requests_list(world.tok["bob"])["requests"] == []


def test_R5_13_participant_handles_not_array_400(world, api):
    t = world.tok["ada"]
    assert_error(split(api, t, 30, "bob"), {400, 422}, {"malformed_request",
                                                        "validation_failed"})
    assert_error(api.post("/splits", t, new_key(), {"amount": 30}), 422, "validation_failed")


def test_R8_57_split_note_length(world, api):
    t = world.tok["ada"]
    assert split(api, t, 30, ["bob"], note="n" * 200).status_code == 201
    assert_error(split(api, t, 30, ["bob"], note="n" * 201), 422, "validation_failed")
    assert_error(split(api, t, 30, ["bob"], note=None), 422, "validation_failed")


def test_R8_58_unknown_participant_404_creates_nothing(world, api):
    assert_error(split(api, world.tok["ada"], 30, ["bob", "nobody", "cy"]), 404, "not_found")
    assert api.requests_list(world.tok["bob"])["requests"] == []
    assert api.requests_list(world.tok["ada"])["requests"] == []


def test_R4_21_split_not_in_feed_requests_visible_to_parties(world, api):
    s = split(api, world.tok["ada"], 300, ["ada", "bob", "cy"]).json()
    for h in world.tok:
        assert api.feed(world.tok[h])["payments"] == []
    assert api.requests_list(world.tok["dee"])["requests"] == []
    rid = s["requests"][0]["request_id"]
    p = api.pay_request(world.tok["bob"], rid, {"visibility": "private"}).json()
    assert [x["payment_id"] for x in api.feed(world.tok["ada"])["payments"]] == [p["payment_id"]]
    assert api.feed(world.tok["dee"])["payments"] == []
