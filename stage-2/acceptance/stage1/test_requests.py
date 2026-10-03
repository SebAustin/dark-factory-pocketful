"""§8 requests: create, pay, decline, cancel, list. Ledger R-4.12-4.17, R-8.14-8.48."""
import time

import pytest

from conftest import REQUEST_KEYS, RFC3339, assert_error, new_key


def make_req(api, w, requester="bob", payer="ada", amount=1200, **fields):
    r = api.request(w.tok[requester], payer, amount, **fields)
    assert r.status_code == 201, r.text
    return r.json()


def test_R8_16_R1_1_create_request_201(world, api):
    r = api.request(world.tok["bob"], "ada", 1200, note="taxi")
    assert r.status_code == 201
    q = r.json()
    assert set(q) == REQUEST_KEYS, set(q) ^ REQUEST_KEYS
    assert (q["requester_id"], q["requester_handle"]) == ("u_bob", "bob")
    assert (q["payer_id"], q["payer_handle"]) == ("u_ada", "ada")
    assert (q["amount"], q["currency"], q["note"], q["status"]) == (1200, "EUR", "taxi",
                                                                    "pending")
    assert q["payment_id"] is None
    assert RFC3339.match(q["created_at"])
    # creating a request moves nothing
    assert api.balance(world.tok["ada"]) == 10000 and api.balance(world.tok["bob"]) == 2500


def test_R8_17_request_amount_bounds(world, api):
    t = world.tok["bob"]
    for bad in (0, -1, 1_000_000_001, 1.5, True, "5", None):
        assert_error(api.request(t, "ada", bad), 422, "validation_failed")
    assert api.request(t, "ada", 1_000_000_000).status_code == 201
    assert api.request(t, "ada", 1).status_code == 201


def test_R8_18_self_request_422(world, api):
    assert_error(api.request(world.tok["bob"], "bob", 5), 422, "self_request")


def test_R8_19_request_note_length(world, api):
    assert api.request(world.tok["bob"], "ada", 5, note="n" * 200).status_code == 201
    assert_error(api.request(world.tok["bob"], "ada", 5, note="n" * 201), 422,
                 "validation_failed")


def test_R8_22_request_note_default_and_type(world, api):
    q = api.request(world.tok["bob"], "ada", 5).json()
    assert q["note"] == ""
    assert_error(api.request(world.tok["bob"], "ada", 5, note=None), 422, "validation_failed")


def test_R8_20_request_unknown_payer_404(world, api):
    assert_error(api.request(world.tok["bob"], "nobody", 5), 404, "not_found")


def test_R4_17_request_has_no_visibility_field(world, api):
    q = api.request(world.tok["bob"], "ada", 5, visibility="private").json()
    assert "visibility" not in q


def test_R4_14_R8_21_request_above_payer_balance_201_pending(world, api):
    q = make_req(api, world, requester="ada", payer="cy", amount=1_000_000_000)
    assert q["status"] == "pending"
    assert api.requests_list(world.tok["cy"])["requests"][0]["status"] == "pending"


def test_R4_15_R8_29_pay_short_409_then_funded_201(world, api):
    q = make_req(api, world, requester="ada", payer="cy", amount=300)
    key = new_key()
    assert_error(api.pay_request(world.tok["cy"], q["request_id"], {}, key=key), 409,
                 "insufficient_funds")
    assert api.balance(world.tok["cy"]) == 0
    assert api.requests_list(world.tok["cy"])["requests"][0]["status"] == "pending"
    api.pay(world.tok["dee"], "cy", 300)
    r = api.pay_request(world.tok["cy"], q["request_id"], {}, key=key)
    assert r.status_code == 201
    assert api.balance(world.tok["cy"]) == 0
    assert api.balance(world.tok["ada"]) == 10300


def test_R8_26_R4_11_pay_creates_payment_with_request_id(world, api):
    q = make_req(api, world, amount=1200, note="taxi")
    r = api.pay_request(world.tok["ada"], q["request_id"], {"visibility": "public"})
    assert r.status_code == 201
    p = r.json()
    from conftest import PAYMENT_KEYS
    assert set(p) == PAYMENT_KEYS, set(p) ^ PAYMENT_KEYS
    assert (p["from_user_id"], p["from_handle"]) == ("u_ada", "ada")
    assert (p["to_user_id"], p["to_handle"]) == ("u_bob", "bob")
    assert p["amount"] == 1200 and p["currency"] == "EUR"
    assert p["request_id"] == q["request_id"]
    assert p["settlement_id"] is None
    assert api.balance(world.tok["ada"]) == 8800
    assert api.balance(world.tok["bob"]) == 3700


def test_R8_27_pay_marks_request_paid_with_payment_id(world, api):
    q = make_req(api, world)
    p = api.pay_request(world.tok["ada"], q["request_id"]).json()
    for h in ("ada", "bob"):
        got = api.requests_list(world.tok[h])["requests"][0]
        assert got["status"] == "paid"
        assert got["payment_id"] == p["payment_id"]


def test_R8_24_pay_default_public(world, api):
    q = make_req(api, world)
    assert api.pay_request(world.tok["ada"], q["request_id"], {}).json()["visibility"] == "public"


def test_R4_16_R8_24_pay_visibility_private_sets_payment(world, api):
    q = make_req(api, world)
    p = api.pay_request(world.tok["ada"], q["request_id"], {"visibility": "private"}).json()
    assert p["visibility"] == "private"
    assert api.feed(world.tok["cy"])["payments"] == []
    assert [x["payment_id"] for x in api.feed(world.tok["bob"])["payments"]] == [p["payment_id"]]


def test_R8_24_pay_visibility_invalid_422(world, api):
    q = make_req(api, world)
    for vis in ("friends", None, 3):
        assert_error(api.pay_request(world.tok["ada"], q["request_id"], {"visibility": vis}),
                     422, "validation_failed")


def test_R4_13_R8_30_requester_cannot_pay_403(world, api):
    q = make_req(api, world)
    assert_error(api.pay_request(world.tok["bob"], q["request_id"]), 403, "forbidden")
    assert api.balance(world.tok["bob"]) == 2500


def test_R8_30_third_party_pay_403_or_404(world, api):
    q = make_req(api, world)
    assert_error(api.pay_request(world.tok["dee"], q["request_id"]), {403, 404},
                 {"forbidden", "not_found"})
    assert api.balance(world.tok["dee"]) == 5000


def test_R8_31_R8_40_unknown_request_404(world, api):
    assert_error(api.pay_request(world.tok["ada"], "rq_does_not_exist"), 404, "not_found")
    for action in ("decline", "cancel"):
        assert_error(api.post(f"/requests/rq_does_not_exist/{action}", world.tok["ada"]), 404,
                     "not_found")


def test_R8_28_pay_non_pending_409(world, api):
    paid = make_req(api, world)
    api.pay_request(world.tok["ada"], paid["request_id"])
    assert_error(api.pay_request(world.tok["ada"], paid["request_id"]), 409,
                 "request_not_pending")
    declined = make_req(api, world)
    api.post(f"/requests/{declined['request_id']}/decline", world.tok["ada"])
    assert_error(api.pay_request(world.tok["ada"], declined["request_id"]), 409,
                 "request_not_pending")
    cancelled = make_req(api, world)
    api.post(f"/requests/{cancelled['request_id']}/cancel", world.tok["bob"])
    assert_error(api.pay_request(world.tok["ada"], cancelled["request_id"]), 409,
                 "request_not_pending")
    assert api.balance(world.tok["ada"]) == 8800


def test_R8_33_pay_precedence(world, api):
    q = make_req(api, world, requester="ada", payer="bob", amount=2000)
    assert api.pay_request(world.tok["bob"], q["request_id"]).status_code == 201
    # payer now short (500 left) and request paid -> request_not_pending, not insufficient
    big = make_req(api, world, requester="ada", payer="bob", amount=2000)
    api.post(f"/requests/{big['request_id']}/decline", world.tok["bob"])
    assert_error(api.pay_request(world.tok["bob"], big["request_id"]), 409,
                 "request_not_pending")
    # requester on a paid request -> 403 (permission before state)
    assert_error(api.pay_request(world.tok["ada"], q["request_id"]), 403, "forbidden")


def test_R8_34_decline_200_no_key_needed(world, api):
    q = make_req(api, world)
    r = api.post(f"/requests/{q['request_id']}/decline", world.tok["ada"])
    assert r.status_code == 200
    body = r.json()
    assert set(body) == REQUEST_KEYS
    assert body["status"] == "declined" and body["request_id"] == q["request_id"]
    assert body["payment_id"] is None


def test_R8_35_decline_twice_200(world, api):
    q = make_req(api, world)
    api.post(f"/requests/{q['request_id']}/decline", world.tok["ada"])
    r = api.post(f"/requests/{q['request_id']}/decline", world.tok["ada"])
    assert r.status_code == 200 and r.json()["status"] == "declined"


def test_R8_36_decline_paid_or_cancelled_409(world, api):
    paid = make_req(api, world)
    api.pay_request(world.tok["ada"], paid["request_id"])
    assert_error(api.post(f"/requests/{paid['request_id']}/decline", world.tok["ada"]), 409,
                 "request_not_pending")
    canc = make_req(api, world)
    api.post(f"/requests/{canc['request_id']}/cancel", world.tok["bob"])
    assert_error(api.post(f"/requests/{canc['request_id']}/decline", world.tok["ada"]), 409,
                 "request_not_pending")


def test_R4_13_R8_36_requester_cannot_decline_403(world, api):
    q = make_req(api, world)
    assert_error(api.post(f"/requests/{q['request_id']}/decline", world.tok["bob"]), 403,
                 "forbidden")
    assert_error(api.post(f"/requests/{q['request_id']}/decline", world.tok["dee"]), {403, 404},
                 {"forbidden", "not_found"})


def test_R8_37_cancel_200_no_key_needed(world, api):
    q = make_req(api, world)
    r = api.post(f"/requests/{q['request_id']}/cancel", world.tok["bob"])
    assert r.status_code == 200
    assert set(r.json()) == REQUEST_KEYS
    assert r.json()["status"] == "cancelled"


def test_R8_38_cancel_twice_200(world, api):
    q = make_req(api, world)
    api.post(f"/requests/{q['request_id']}/cancel", world.tok["bob"])
    r = api.post(f"/requests/{q['request_id']}/cancel", world.tok["bob"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_R8_39_cancel_paid_or_declined_409(world, api):
    paid = make_req(api, world)
    api.pay_request(world.tok["ada"], paid["request_id"])
    assert_error(api.post(f"/requests/{paid['request_id']}/cancel", world.tok["bob"]), 409,
                 "request_not_pending")
    dec = make_req(api, world)
    api.post(f"/requests/{dec['request_id']}/decline", world.tok["ada"])
    assert_error(api.post(f"/requests/{dec['request_id']}/cancel", world.tok["bob"]), 409,
                 "request_not_pending")


def test_R4_13_R8_39_payer_cannot_cancel_403(world, api):
    q = make_req(api, world)
    assert_error(api.post(f"/requests/{q['request_id']}/cancel", world.tok["ada"]), 403,
                 "forbidden")
    assert_error(api.post(f"/requests/{q['request_id']}/cancel", world.tok["dee"]), {403, 404},
                 {"forbidden", "not_found"})


def test_R4_12_terminal_states_are_final(world, api):
    q = make_req(api, world)
    api.post(f"/requests/{q['request_id']}/cancel", world.tok["bob"])
    api.post(f"/requests/{q['request_id']}/decline", world.tok["ada"])
    api.pay_request(world.tok["ada"], q["request_id"])
    assert api.requests_list(world.tok["bob"])["requests"][0]["status"] == "cancelled"
    assert api.balance(world.tok["ada"]) == 10000


# ---------- GET /requests ----------

def test_R4_20_R8_41_list_only_own_requests(world, api):
    make_req(api, world, requester="bob", payer="ada")
    make_req(api, world, requester="dee", payer="bob")
    assert api.requests_list(world.tok["cy"])["requests"] == []
    ada = api.requests_list(world.tok["ada"])["requests"]
    assert len(ada) == 1 and ada[0]["requester_handle"] == "bob"
    assert len(api.requests_list(world.tok["bob"])["requests"]) == 2


def test_R8_48_list_shape(world, api):
    make_req(api, world)
    body = api.requests_list(world.tok["ada"])
    assert set(body) == {"requests", "has_more"}
    assert body["has_more"] is False
    assert set(body["requests"][0]) == REQUEST_KEYS


def test_R8_42_list_newest_first(world, api):
    ids = []
    for i in range(3):
        ids.append(make_req(api, world, amount=10 + i)["request_id"])
        if i < 2:
            time.sleep(1.1)  # distinct created_at seconds; same-second order is unspecified
    got = [q["request_id"] for q in api.requests_list(world.tok["ada"])["requests"]]
    assert got == list(reversed(ids))


def test_R8_43_list_direction_filter(world, api):
    inc = make_req(api, world, requester="bob", payer="ada")["request_id"]
    out = make_req(api, world, requester="ada", payer="dee")["request_id"]
    t = world.tok["ada"]
    assert [q["request_id"] for q in api.requests_list(t, direction="incoming")["requests"]] == \
        [inc]
    assert [q["request_id"] for q in api.requests_list(t, direction="outgoing")["requests"]] == \
        [out]
    assert {q["request_id"] for q in api.requests_list(t)["requests"]} == {inc, out}


def test_R8_44_list_status_filter(world, api):
    t = world.tok
    pend = make_req(api, world)["request_id"]
    paid = make_req(api, world)["request_id"]
    api.pay_request(t["ada"], paid)
    dec = make_req(api, world)["request_id"]
    api.post(f"/requests/{dec}/decline", t["ada"])
    can = make_req(api, world)["request_id"]
    api.post(f"/requests/{can}/cancel", t["bob"])
    for status, rid in (("pending", pend), ("paid", paid), ("declined", dec),
                        ("cancelled", can)):
        got = api.requests_list(t["ada"], status=status)["requests"]
        assert [q["request_id"] for q in got] == [rid], status
        assert got[0]["status"] == status
    both = api.requests_list(t["ada"], status="pending", direction="outgoing")["requests"]
    assert both == []


def test_R8_46_list_unknown_direction_status_422(world, api):
    t = world.tok["ada"]
    for params in ({"direction": "INCOMING"}, {"direction": ""}, {"direction": "both"},
                   {"status": "accepted"}, {"status": ""}, {"status": "PAID"}):
        assert_error(api.get("/requests", t, params=params), 422, "validation_failed")


def test_R8_45_R5_17_list_limit_bounds(world, api):
    t = world.tok["ada"]
    for bad in ("0", "201", "-1"):
        assert_error(api.get("/requests", t, params={"limit": bad}), 422, "validation_failed")
    for ok in ("1", "200"):
        assert api.get("/requests", t, params={"limit": ok}).status_code == 200
    assert_error(api.get("/requests", t, params={"offset": "-1"}), 422, "validation_failed")


@pytest.mark.parametrize("bad", ["1e9", "4.0", "+4", "abc", "", " 4", "0x10"])
def test_R5_14_list_query_int_non_decimal_422(world, api, bad):
    t = world.tok["ada"]
    assert_error(api.get("/requests", t, params={"limit": bad}), 422, "validation_failed")
    assert_error(api.get("/requests", t, params={"offset": bad}), 422, "validation_failed")


def test_R8_45_list_default_limit_50(world, api):
    for _ in range(55):
        api.request(world.tok["bob"], "ada", 1)
    body = api.requests_list(world.tok["ada"])
    assert len(body["requests"]) == 50 and body["has_more"] is True
    rest = api.requests_list(world.tok["ada"], offset=50)
    assert len(rest["requests"]) == 5 and rest["has_more"] is False


def test_R8_47_list_has_more_exact_boundary(world, api):
    for _ in range(4):
        api.request(world.tok["bob"], "ada", 1)
    t = world.tok["ada"]
    assert api.requests_list(t, limit=4)["has_more"] is False
    assert api.requests_list(t, limit=3)["has_more"] is True
    assert api.requests_list(t, limit=2, offset=2)["has_more"] is False
    r = api.requests_list(t, offset=4)
    assert r["requests"] == [] and r["has_more"] is False
    pages = api.requests_list(t, limit=2)["requests"] + \
        api.requests_list(t, limit=2, offset=2)["requests"]
    assert len({q["request_id"] for q in pages}) == 4


def test_R3_11_list_unknown_query_param_ignored(world, api):
    make_req(api, world)
    r = api.get("/requests", world.tok["ada"], params={"colour": "teal", "sort": "x"})
    assert r.status_code == 200 and len(r.json()["requests"]) == 1
