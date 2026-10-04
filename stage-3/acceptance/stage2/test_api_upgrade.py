"""Upgrade: a stage-1 export imported into stage 2, and stage-2 round trips.

Ledger R2-UPG.1/2/3/4/7, R2-EXP.7, R-10.x as changed. Needs the team's stage-1 image running at
STAGE1_URL (default http://127.0.0.1:18101); see README.
"""
from datetime import timedelta

import pytest

from s2lib import (Api, PASSWORD, STAGE1_URL, assert_error, auth_rec, fixture, new_key, parse_ts,
                   user)


def stage1_fixture():
    return {"currency": "EUR", "minor_units": 2,
            "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                      user("u_cy", "cy", 0)],
            "payments": [], "requests": []}


@pytest.fixture
def s1():
    a = Api(STAGE1_URL)
    try:
        a.get("/health")
    except Exception as exc:  # the upgrade rows cannot be judged without the stage-1 service
        pytest.fail(f"stage-1 service not reachable at {STAGE1_URL}: {exc}")
    yield a
    a.http.close()


def build_stage1_state(s1):
    s1.reset(stage1_fixture())
    tok = {h: s1.login(f"{h}@example.com") for h in ("ada", "bob", "cy")}
    rec = {"tok": tok}
    rec["pay_key"] = new_key()
    rec["pay_body"] = {"to_handle": "bob", "amount": 300, "note": "lost one"}
    r = s1.post("/payments", tok["ada"], rec["pay_key"], rec["pay_body"])
    assert r.status_code == 201
    rec["pay"] = r.json()
    rec["req"] = s1.request(tok["bob"], "ada", 700).json()
    rec["export"] = s1.export()
    return rec


def test_R2_UPG_1_stage1_export_imports_into_stage2(s1, api):
    rec = build_stage1_state(s1)
    assert rec["export"]["track"] == "pocketful" and rec["export"]["format_version"] == 1
    r = api.import_(rec["export"])
    assert r.status_code == 204, r.text
    for h, t in rec["tok"].items():
        m = api.me(t)  # stage-1 tokens still valid
        assert m["total"] == m["available"] == m["balance"] and m["held"] == 0
    assert api.me(rec["tok"]["ada"])["total"] == 9700
    assert api.login("ada@example.com", PASSWORD)


def test_R2_UPG_3_imported_pending_request_payable(s1, api):
    rec = build_stage1_state(s1)
    api.import_(rec["export"])
    rid = rec["req"]["request_id"]
    r = api.post(f"/requests/{rid}/pay", rec["tok"]["ada"], new_key(), {})
    assert r.status_code == 201, r.text
    assert r.json()["authorization_id"] is None
    assert api.me(rec["tok"]["bob"])["total"] == 2500 + 300 + 700


def test_R2_UPG_4_lost_payment_replays_after_import(s1, api):
    rec = build_stage1_state(s1)
    api.import_(rec["export"])
    r = api.post("/payments", rec["tok"]["ada"], rec["pay_key"], rec["pay_body"])
    assert r.status_code == 200, r.text
    assert r.json() == rec["pay"]                      # the stored original (D-34)
    assert api.me(rec["tok"]["ada"])["total"] == 9700  # no second debit
    r = api.post("/payments", rec["tok"]["ada"], rec["pay_key"], {**rec["pay_body"], "amount": 1})
    assert_error(r, 409, "idempotency_key_reuse")


def test_R2_UPG_2_stage2_session_survives_stage1_upgrade(s1, api):
    """A browser signed in on the stage-2 service before the upgrade stays signed in (D-22)."""
    api.reset(fixture(users=[user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                             user("u_cy", "cy", 0)], settlement_operator_ids=[]))
    stage2_token = api.login("ada@example.com")
    rec = build_stage1_state(s1)
    assert api.import_(rec["export"]).status_code == 204
    m = api.me(stage2_token)
    assert m["user_id"] == "u_ada" and m["total"] == 9700


def test_R2_UPG_7_EXP_7_stage2_export_import_preserves_holds_and_receipts(make_world, api):
    fx = fixture(authorization_ttl_seconds=1234,
                 authorizations=[auth_rec("a_seed", "u_dee", "u_cy", 1000)])
    w = make_world(fx)
    a = api.authorize(w.tok["ada"], "bob", 2000).json()
    ckey = new_key()
    cap = api.capture(w.tok["bob"], a["authorization_id"], {"amount": 500, "final": False},
                      key=ckey).json()
    akey = new_key()
    a2 = api.authorize(w.tok["ada"], "cy", 10, key=akey).json()
    before = w.mes()
    lists = {h: api.auths(t, limit=200) for h, t in w.tok.items()}
    exp = api.export()
    api.reset(fixture())
    assert api.import_(exp).status_code == 204
    assert w.mes() == before
    assert {h: api.auths(t, limit=200) for h, t in w.tok.items()} == lists
    again = api.capture(w.tok["bob"], a["authorization_id"], {"amount": 500, "final": False},
                        key=ckey)
    assert again.status_code == 200 and again.json() == cap
    assert api.authorize(w.tok["ada"], "cy", 10, key=akey).json() == a2
    n = api.authorize(w.tok["ada"], "cy", 1).json()
    assert parse_ts(n["expires_at"]) - parse_ts(n["created_at"]) == timedelta(seconds=1234)
    w.assert_invariants()


# ---------------------------------------------------------------- D-22 / lead decision L5

def test_R2_UPG_2_D22_stage1_import_drops_tokens_of_mismatched_users(s1, api):
    """Kept only when the same id, email AND handle exist in the imported state."""
    api.reset(fixture(users=[user("u_ada", "ada", 10000),       # same id/email/handle: kept
                             user("u_bob", "bobby", 2500),       # same id, other handle
                             user("u_cy", "cy", 0, email="cy@other.org"),  # other email
                             user("u_zed", "zed", 0)],           # not in the import
                      settlement_operator_ids=[]))
    toks = {h: api.login(e) for h, e in (("ada", "ada@example.com"), ("bobby", "bobby@example.com"),
                                         ("cy", "cy@other.org"), ("zed", "zed@example.com"))}
    rec = build_stage1_state(s1)
    assert api.import_(rec["export"]).status_code == 204
    assert api.me(toks["ada"])["user_id"] == "u_ada"
    for h in ("bobby", "cy", "zed"):
        assert_error(api.get("/me", toks[h]), 401, "unauthenticated")
    for t in rec["tok"].values():                      # the export's own tokens survive
        assert api.get("/me", t).status_code == 200


def test_R2_UPG_2_D22_stage2_import_is_pure_replacement(make_world, api):
    w = make_world(fixture())
    exported = api.export()
    late = api.login("ada@example.com")                # minted after the export
    assert api.import_(exported).status_code == 204
    assert_error(api.get("/me", late), 401, "unauthenticated")
    assert api.get("/me", w.tok["ada"]).status_code == 200   # exported token survives
