"""Payment timestamps, seeding, and GET /me as of an instant. Ledger R3-TS, R3-ME, R3-REV.4/6."""
from datetime import datetime, timedelta

import pytest

from s3lib import (CONTROL_TIMEOUT, PAYMENT_KEYS, RFC3339, US, UTC, assert_error, base_fixture,
                   iso, iso_ns, new_key, ns, now_ns, user)

STAGE2_ME_KEYS = {"user_id", "display_name", "handle", "balance", "total", "available", "held",
                  "currency", "minor_units"}


# ---------------------------------------------------------------- TS

def test_R3_TS_1_TS_2_created_at_on_every_payment_surface(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 100)
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 50}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    st = api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "dee", "to_handle": "cy", "amount": 10}]}).json()
    a = api.call("POST", "/authorizations", tk["ada"], new_key(),
                 {"to_handle": "bob", "amount": 30}).json()
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                   new_key(), {}).json()
    for obj in (p, rp, st["payments"][0], cap):
        assert set(obj) == PAYMENT_KEYS and RFC3339.match(obj["created_at"]), obj
    for x in api.call("GET", "/activity", tk["ada"], params={"limit": 200}).json()["payments"]:
        assert RFC3339.match(x["created_at"])
    r = api.statement(tk["ada"])
    assert r.status_code == 200, r.text
    for e in r.json()["entries"]:
        assert RFC3339.match(e["payment"]["created_at"])


def test_R3_TS_3_activity_order_by_created_at_incl_seeded_past(world, api):
    p = world.pay("ada", "bob", 1)
    ids = [x["payment_id"] for x in api.call("GET", "/activity", world.tok["ada"]).json()[
        "payments"]]
    assert ids == [p["payment_id"], "p_s2", "p_s1"]


def test_R3_TS_4_TS_8_seeded_created_at_kept_as_revision1(world, api):
    fx_time = world.fx["payments"][0]["created_at"]
    feed = {x["payment_id"]: x for x in api.call("GET", "/activity", world.tok["bob"]).json()[
        "payments"]}
    assert ns(feed["p_s1"]["created_at"]) == ns(fx_time)
    r = api.revisions(world.tok["bob"], "p_s1")
    assert r.status_code == 200, r.text
    rev = r.json()["revisions"]
    assert len(rev) == 1 and rev[0]["revision"] == 1 and rev[0]["reason"] == ""
    assert ns(rev[0]["effective_at"]) == ns(rev[0]["recorded_at"]) == ns(fx_time)
    assert rev[0]["amount"] == 500


def test_R3_TS_5_omitted_created_at_is_reset_time_before_api_payments(api):
    fx = base_fixture()
    fx["payments"].append({"id": "p_zz_noclock", "from_user_id": "u_dee",
                           "to_user_id": "u_bob", "amount": 7, "note": "", "visibility": "public"})
    before = now_ns()
    api.reset(fx)
    after = now_ns()
    dee = api.login("dee@example.com")
    api.pay(dee, "bob", 3)                      # immediately after reset
    feed = api.call("GET", "/activity", dee).json()["payments"]
    assert feed[1]["payment_id"] == "p_zz_noclock"
    seeded_t = ns(feed[1]["created_at"])
    assert before - 2 * 10 ** 9 <= seeded_t <= after + 2 * 10 ** 9   # reset time
    assert ns(feed[0]["created_at"]) > seeded_t
    st = api.statement(dee).json()["entries"]
    assert [e["payment"]["payment_id"] for e in st][-2:] == ["p_zz_noclock",
                                                             feed[0]["payment_id"]]


def test_R3_TS_6_seeded_future_created_at_422_state_unchanged(world, api):
    world.pay("ada", "bob", 100)
    fx = base_fixture()
    fx["payments"][1]["created_at"] = iso(datetime.now(UTC) + timedelta(seconds=30))
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")
    assert api.me(world.tok["ada"])["balance"] == 9900          # nothing changed
    fx["payments"][1]["created_at"] = iso(datetime.now(UTC) - timedelta(seconds=1))
    api.reset(fx)


def test_R3_TS_7_seeded_balance_is_ending_balance(world, api):
    for h, bal in (("ada", 10000), ("bob", 2500), ("cy", 1500), ("dee", 5000)):
        assert api.me(world.tok[h])["balance"] == bal


def test_R3_TS_9_inconsistent_seeded_history_422(api):
    fx = base_fixture(users=[user("u_ada", "ada", 100), user("u_bob", "bob", 0)],
                      settlement_operator_ids=[])
    fx["payments"] = [{"id": "p_bad", "from_user_id": "u_bob", "to_user_id": "u_ada",
                       "amount": 50, "note": "", "visibility": "public",
                       "created_at": iso(datetime.now(UTC) - timedelta(hours=1))}]
    # bob ends at 0 after sending 50, so bob opened at 50 and ada at 50: consistent
    api.reset(fx)
    fx["users"][0]["balance"] = 10   # ada would have opened at -40
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


def test_R3_TS_10_server_instants_strictly_increase(world, api):
    ts = [ns(world.pay("ada", "bob", 1)["created_at"]) for _ in range(30)]
    assert all(b > a for a, b in zip(ts, ts[1:])), ts


def test_R3_TS_11_equal_created_at_tiebreak_by_id(api):
    t = iso(datetime.now(UTC) - timedelta(hours=1))
    fx = base_fixture()
    fx["payments"] = [
        {"id": "p_b", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1, "note": "",
         "visibility": "public", "created_at": t},
        {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2, "note": "",
         "visibility": "public", "created_at": t},
        {"id": "p_10", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 4, "note": "",
         "visibility": "public", "created_at": t},
    ]
    api.reset(fx)
    ada = api.login("ada@example.com")
    r = api.statement(ada)
    assert r.status_code == 200, r.text
    assert [e["payment"]["payment_id"] for e in r.json()["entries"]] == ["p_10", "p_a", "p_b"]
    # all three count at exactly t (as_of inclusive), none at t-1us
    m = api.me(ada, as_of=t)
    assert m["balance"] == 10000
    assert api.me(ada, as_of=iso_ns(ns(t) - US))["balance"] == 10007


# ---------------------------------------------------------------- ME

def test_R3_ME_1_as_of_accepts_offsets_same_instant(world, api):
    t = ns(world.fx["payments"][1]["created_at"])
    forms = [iso_ns(t), iso_ns(t, 120), iso_ns(t, -330),
             iso_ns(t).replace("+00:00", "Z").replace("000+", "+")]
    vals = {api.me(world.tok["ada"], as_of=f)["balance"] for f in forms}
    assert vals == {10000}


@pytest.mark.parametrize("bad", ["2026-09-24T13:20:00", "2026-09-24", "", "now", "1727184000",
                                 "2026-13-01T00:00:00Z", "2026-09-24 13:20:00Z",
                                 "2026-09-24T13:20:00+24:00", "2026-09-24T25:00:00Z",
                                 "2026-02-30T00:00:00Z", "2026-09-24T13:20:00.1234567890Z"])
def test_R3_ME_2_KN_5_invalid_instants_422(world, api, bad):
    for param in ("as_of", "known_at"):
        r = api.call("GET", "/me", world.tok["ada"], params={param: bad})
        assert_error(r, 422, "validation_failed")


def test_R3_ME_3_no_params_shape_unchanged(world, api):
    m = api.me(world.tok["ada"])
    assert set(m) == STAGE2_ME_KEYS


def test_R3_ME_4_ME_7_REV_4_as_of_steps(world, api):
    s1 = world.fx["payments"][0]["created_at"]
    s2 = world.fx["payments"][1]["created_at"]
    t = world.tok["ada"]
    assert api.me(t, as_of=iso_ns(ns(s1) - US))["balance"] == 12000        # opening
    assert api.me(t, as_of=s1)["balance"] == 11500                         # inclusive
    assert api.me(t, as_of=iso_ns(ns(s2) - US))["balance"] == 11500
    assert api.me(t, as_of=s2)["balance"] == 10000
    assert api.me(world.tok["cy"], as_of=iso_ns(ns(s2) - US))["balance"] == 0
    assert api.me(t, as_of="1970-01-01T00:00:00Z")["balance"] == 12000


def test_R3_ME_5_inclusive_at_exact_instant_any_offset(world, api):
    p = world.pay("ada", "bob", 250)
    t = ns(p["created_at"])
    for off in (0, 60, -480):
        assert api.me(world.tok["ada"], as_of=iso_ns(t, off))["balance"] == 9750
        assert api.me(world.tok["ada"], as_of=iso_ns(t - US, off))["balance"] == 10000


def test_R3_ME_6_after_latest_is_current(world, api):
    world.pay("ada", "bob", 250)
    for T in (iso_ns(now_ns() + 10 ** 9), "2999-01-01T00:00:00Z"):
        m = api.me(world.tok["ada"], as_of=T)
        assert m["balance"] == 9750 == api.me(world.tok["ada"])["balance"]


def test_R3_ME_8_ME_10_echo_verbatim(world, api):
    forms = ["2026-01-02T03:04:05.120+05:30", "2026-01-02t03:04:05z"]
    for f in forms:
        m = api.me(world.tok["ada"], as_of=f, known_at=f)
        assert m["as_of"] == f and m["known_at"] == f
    m = api.me(world.tok["ada"], as_of=forms[0])
    assert "known_at" not in m
    m = api.me(world.tok["ada"], known_at=forms[0])
    assert "as_of" not in m


def test_R3_ME_9_four_fields_same_view(world, api):
    a = api.call("POST", "/authorizations", world.tok["ada"], new_key(),
                 {"to_handle": "bob", "amount": 2000}).json()
    t = ns(a["created_at"])
    m = api.me(world.tok["ada"], as_of=iso_ns(t))
    assert (m["balance"], m["total"], m["held"], m["available"]) == (10000, 10000, 2000, 8000)
    m = api.me(world.tok["ada"], as_of=iso_ns(t - US))
    assert (m["total"], m["held"], m["available"]) == (10000, 0, 10000)


def test_R3_REV_6_signup_opens_at_zero(world, api):
    r = api.call("POST", "/auth/signup", json={"email": "new@example.com",
                                               "password": "longenough",
                                               "display_name": "New"})
    tok = r.json()["token"]
    p = world.pay("ada", "new", 300)
    assert api.me(tok, as_of=iso_ns(ns(p["created_at"]) - US))["balance"] == 0
    assert api.me(tok, as_of="1970-01-01T00:00:00Z")["balance"] == 0
    assert api.me(tok)["balance"] == 300
