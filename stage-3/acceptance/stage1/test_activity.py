"""§4 feed contract and §8 GET /activity. Ledger R-1.2, R-4.17-4.22, R-8.61-8.64, R-5.14/17/18."""
import time

import pytest

from conftest import PAYMENT_KEYS, assert_error, base_fixture


def ids(items):
    return {p["payment_id"] for p in items}


def test_R4_18_R1_2_feed_contract_matrix(make_world, api):
    fx = base_fixture(payments=[
        {"id": "p_seed_pub", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
         "note": "", "visibility": "public"},
        {"id": "p_seed_priv", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
         "note": "", "visibility": "private"},
    ])
    w = make_world(fx)
    pub = api.pay(w.tok["ada"], "bob", 10, visibility="public").json()["payment_id"]
    priv = api.pay(w.tok["ada"], "bob", 10, visibility="private").json()["payment_id"]
    everything = {"p_seed_pub", "p_seed_priv", pub, priv}
    assert ids(api.feed(w.tok["ada"])["payments"]) == everything      # sender
    assert ids(api.feed(w.tok["bob"])["payments"]) == everything      # receiver
    assert ids(api.feed(w.tok["cy"])["payments"]) == {"p_seed_pub", pub}  # third party
    assert ids(api.feed(w.tok["dee"])["payments"]) == {"p_seed_pub", pub}


def test_R4_19_third_party_sees_public_between_strangers(world, api):
    pid = api.pay(world.tok["bob"], "cy", 5).json()["payment_id"]
    assert ids(api.feed(world.tok["dee"])["payments"]) == {pid}


def test_R4_22_private_visible_to_receiver_same_value(world, api):
    p = api.pay(world.tok["ada"], "bob", 5, visibility="private").json()
    a = api.feed(world.tok["ada"])["payments"][0]
    b = api.feed(world.tok["bob"])["payments"][0]
    assert a == b == p
    assert a["visibility"] == "private"


def test_R4_17_requests_never_in_feed(world, api):
    api.request(world.tok["bob"], "ada", 5)
    api.post("/splits", world.tok["ada"], "k-split",
             {"amount": 9, "participant_handles": ["bob", "cy"]})
    for t in world.tok.values():
        assert api.feed(t)["payments"] == []


def test_R8_62_feed_shape(world, api):
    api.pay(world.tok["ada"], "bob", 5)
    body = api.feed(world.tok["ada"])
    assert set(body) == {"payments", "has_more"}
    assert body["has_more"] is False
    assert set(body["payments"][0]) == PAYMENT_KEYS


def test_R8_61_feed_newest_first(world, api):
    order = []
    for i in range(3):
        order.append(api.pay(world.tok["ada"], "bob", 1 + i).json()["payment_id"])
        if i < 2:
            time.sleep(1.1)  # distinct seconds; same-second order is unspecified (R-8.63)
    got = [p["payment_id"] for p in api.feed(world.tok["cy"])["payments"]]
    assert got == list(reversed(order))


def test_R8_64_R5_17_limit_bounds(world, api):
    t = world.tok["ada"]
    for bad in ("0", "201", "-5"):
        assert_error(api.get("/activity", t, params={"limit": bad}), 422, "validation_failed")
    for ok in ("1", "200", "50"):
        assert api.get("/activity", t, params={"limit": ok}).status_code == 200


def test_R8_64_R5_18_offset_bounds(world, api):
    t = world.tok["ada"]
    assert_error(api.get("/activity", t, params={"offset": "-1"}), 422, "validation_failed")
    assert api.get("/activity", t, params={"offset": "0"}).status_code == 200
    r = api.get("/activity", t, params={"offset": "100000"})
    assert r.status_code == 200 and r.json() == {"payments": [], "has_more": False}


@pytest.mark.parametrize("bad", ["1e9", "4.0", "+4", "-0", " 4", "abc", "", "1_0"])
def test_R5_14_query_int_non_decimal_422(world, api, bad):
    t = world.tok["ada"]
    assert_error(api.get("/activity", t, params={"limit": bad}), 422, "validation_failed")
    assert_error(api.get("/activity", t, params={"offset": bad}), 422, "validation_failed")


def test_R8_64_has_more_boundary(world, api):
    for _ in range(5):
        api.pay(world.tok["ada"], "bob", 1)
    t = world.tok["cy"]
    assert api.feed(t, limit=5)["has_more"] is False
    assert api.feed(t, limit=4)["has_more"] is True
    page2 = api.feed(t, limit=3, offset=3)
    assert len(page2["payments"]) == 2 and page2["has_more"] is False
    pages = api.feed(t, limit=3)["payments"] + page2["payments"]
    assert len(ids(pages)) == 5


def test_R8_64_default_limit_50(world, api):
    for _ in range(53):
        api.pay(world.tok["ada"], "bob", 1)
    body = api.feed(world.tok["dee"])
    assert len(body["payments"]) == 50 and body["has_more"] is True


def test_R3_11_unknown_query_param_ignored(world, api):
    api.pay(world.tok["ada"], "bob", 1)
    r = api.get("/activity", world.tok["ada"], params={"since": "yesterday", "page": "2"})
    assert r.status_code == 200 and len(r.json()["payments"]) == 1
