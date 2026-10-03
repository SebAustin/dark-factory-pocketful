"""§3 runtime contract, §4 fixture, reset. Ledger R-3.x, R-4.1/4.7/4.24-4.29."""
import time

import pytest

from conftest import (CONTROL_TIMEOUT, PASSWORD, RFC3339, assert_error, base_fixture, new_key,
                      user)


def test_R3_2_health_200_status_ok(api):
    r = api.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_R3_8_content_type_json_utf8_on_success_and_error(world, api):
    ok = api.get("/me", world.tok["ada"])
    err = api.get("/me")
    for r in (ok, err):
        ct = r.headers.get("content-type", "").lower().replace(" ", "")
        assert ct.startswith("application/json"), ct
        assert "charset=utf-8" in ct, ct


def test_R3_4_reset_204_empty_body(api):
    r = api.call("POST", "/_test/reset", json=base_fixture(), timeout=CONTROL_TIMEOUT)
    assert r.status_code == 204
    assert r.content == b""


def test_R3_7_reset_without_auth(api):
    r = api.call("POST", "/_test/reset", json=base_fixture(),
                 headers={"Authorization": "Bearer nonsense"}, timeout=CONTROL_TIMEOUT)
    assert r.status_code == 204


def test_R3_5_reset_replaces_users_old_token_401(world, api):
    old = world.tok["ada"]
    fx = base_fixture(users=[user("u_zed", "zed", 700), user("u_yan", "yan", 300)])
    api.reset(fx)
    assert_error(api.get("/me", old), 401, "unauthenticated")
    r = api.post("/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
    assert_error(r, 401, "unauthenticated")
    tok = api.login("zed@example.com")
    assert api.me(tok)["balance"] == 700


def test_R3_5_reset_drops_old_payments_requests(world, api):
    assert api.pay(world.tok["ada"], "bob", 100).status_code == 201
    assert api.request(world.tok["bob"], "ada", 100).status_code == 201
    api.reset(base_fixture())
    ada = api.login("ada@example.com")
    assert api.feed(ada)["payments"] == []
    assert api.requests_list(ada)["requests"] == []
    assert api.balance(ada) == 10000


def test_R3_6_repeated_resets(api):
    for bal in (1, 2, 3):
        api.reset(base_fixture(users=[user("u_a", "aa", bal), user("u_b", "bb", 0)]))
    tok = api.login("aa@example.com")
    assert api.balance(tok) == 3


def test_R4_25_seeded_login_immediately(api):
    api.reset(base_fixture())
    r = api.post("/auth/login", json={"email": "bob@example.com", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u_bob"
    assert body["display_name"] == "Bob"
    assert isinstance(body["token"], str) and body["token"]


def test_R4_26_seeded_payments_not_replayed(make_world, api):
    fx = base_fixture(payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                 "amount": 500, "note": "coffee", "visibility": "public"}])
    w = make_world(fx)
    assert api.balance(w.tok["ada"]) == 10000
    assert api.balance(w.tok["bob"]) == 2500


def test_R4_29_seeded_payment_and_request_visible_with_fixture_ids(make_world, api):
    fx = base_fixture(
        payments=[{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
                   "note": "coffee", "visibility": "public"}],
        requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200,
                   "note": "taxi", "status": "pending"}],
    )
    w = make_world(fx)
    items = api.feed(w.tok["cy"])["payments"]
    assert [p["payment_id"] for p in items] == ["p_1"]
    p = items[0]
    assert (p["from_user_id"], p["from_handle"], p["to_user_id"], p["to_handle"]) == \
        ("u_ada", "ada", "u_bob", "bob")
    assert (p["amount"], p["note"], p["visibility"], p["currency"]) == (500, "coffee", "public",
                                                                        "EUR")
    reqs = api.requests_list(w.tok["ada"])["requests"]
    assert [q["request_id"] for q in reqs] == ["rq_1"]
    q = reqs[0]
    assert (q["requester_id"], q["payer_id"], q["amount"], q["status"], q["note"]) == \
        ("u_bob", "u_ada", 1200, "pending", "taxi")
    # the seeded request is payable (R-4.15)
    r = api.pay_request(w.tok["ada"], "rq_1")
    assert r.status_code == 201
    assert r.json()["request_id"] == "rq_1"


def test_R4_27_negative_balance_422_state_unchanged(world, api):
    old = world.tok["ada"]
    assert api.pay(old, "bob", 100).status_code == 201
    bad = base_fixture(users=[user("u_x", "xx", -1), user("u_y", "yy", 10)])
    r = api.call("POST", "/_test/reset", json=bad, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")
    # nothing changed: old token valid, payment and balances intact
    assert api.balance(old) == 9900
    assert len(api.feed(old)["payments"]) == 1
    r = api.post("/auth/login", json={"email": "xx@example.com", "password": PASSWORD})
    assert_error(r, 401, "unauthenticated")


def test_R4_28_minor_units_invalid_422(api):
    r = api.call("POST", "/_test/reset", json=base_fixture(minor_units=1),
                 timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


def test_R3_5_reset_unparseable_400(api):
    r = api.call("POST", "/_test/reset", content=b"{not json", timeout=CONTROL_TIMEOUT)
    assert_error(r, 400, "malformed_request")


@pytest.mark.parametrize("currency,minor", [("EUR", 2), ("JPY", 0), ("BHD", 3)])
def test_R4_1_R4_28_me_currency_from_fixture(make_world, api, currency, minor):
    w = make_world(currency=currency, minor_units=minor)
    me = api.me(w.tok["ada"])
    assert (me["currency"], me["minor_units"]) == (currency, minor)
    r = api.pay(w.tok["ada"], "bob", 1000)
    assert r.status_code == 201
    assert r.json()["currency"] == currency
    assert r.json()["amount"] == 1000


def test_R8_1_R4_7_me_shape_seeded(world, api):
    me = api.me(world.tok["ada"])
    assert me == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                  "balance": 10000, "currency": "EUR", "minor_units": 2}


def test_R4_24_large_balance_exact(make_world, api):
    big = 2 ** 53 - 1_000_000_001
    w = make_world(users=[user("u_r", "rich", big), user("u_s", "sender", 1_000_000_000)])
    r = api.pay(w.tok["sender"], "rich", 1_000_000_000)
    assert r.status_code == 201
    assert api.balance(w.tok["rich"]) == 2 ** 53 - 1
    assert api.balance(w.tok["sender"]) == 0


def test_R3_10_fixture_unknown_fields_ignored(make_world, api):
    fx = base_fixture()
    fx["extra_top"] = {"x": 1}
    fx["users"][0]["favourite_colour"] = "teal"
    w = make_world(fx)
    assert api.balance(w.tok["ada"]) == 10000


def test_R3_13_generated_ids_do_not_collide_with_fixture_ids(make_world, api):
    seeded_p = [{"id": f"p_{i}", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
                 "note": "", "visibility": "public"} for i in range(1, 21)]
    seeded_p += [{"id": f"pay_{i}", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
                  "note": "", "visibility": "public"} for i in range(1, 6)]
    seeded_r = [{"id": f"rq_{i}", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1,
                 "note": "", "status": "pending"} for i in range(1, 21)]
    w = make_world(base_fixture(payments=seeded_p, requests=seeded_r))
    pids = {p["id"] for p in seeded_p}
    rids = {r["id"] for r in seeded_r}
    for _ in range(25):
        r = api.pay(w.tok["ada"], "cy", 1)
        assert r.status_code == 201
        assert r.json()["payment_id"] not in pids
        pids.add(r.json()["payment_id"])
        q = api.request(w.tok["cy"], "dee", 1)
        assert q.status_code == 201
        assert q.json()["request_id"] not in rids
        rids.add(q.json()["request_id"])
    feed = api.feed(w.tok["ada"], limit=200)["payments"]
    ids = [p["payment_id"] for p in feed]
    assert len(ids) == len(set(ids)) == 50


def test_R2_9_large_fixture_reset_within_10s(api):
    users = [user(f"u_{i}", f"user{i}", 100) for i in range(1000)]
    start = time.monotonic()
    r = api.call("POST", "/_test/reset", json=base_fixture(users=users), timeout=CONTROL_TIMEOUT)
    assert r.status_code == 204
    assert time.monotonic() - start < 10.0
    tok = api.login("user999@example.com")
    assert api.balance(tok) == 100


def test_R3_9_timestamps_rfc3339(world, api):
    p = api.pay(world.tok["ada"], "bob", 1).json()
    q = api.request(world.tok["ada"], "bob", 1).json()
    for ts in (p["created_at"], q["created_at"]):
        assert RFC3339.match(ts), ts


def test_R3_12_ids_are_strings_le_64(world, api):
    p = api.pay(world.tok["ada"], "bob", 1).json()
    q = api.request(world.tok["ada"], "bob", 1).json()
    s = api.post("/splits", world.tok["ada"], new_key(),
                 {"amount": 3, "participant_handles": ["ada", "bob"]}).json()
    signup = api.post("/auth/signup", json={"email": "newbie@example.com",
                                            "password": "longenough", "display_name": "N"}).json()
    for v in (p["payment_id"], q["request_id"], s["split_id"], signup["user_id"]):
        assert isinstance(v, str) and 1 <= len(v) <= 64, v
