"""Upgrades from populated stage 1, 2 and 3 exports; stage-4 snapshot round trip (L10).

Ledger R4-UPG.1/2/4/5, R4-RSH.8. Needs STAGE1_URL, STAGE2_URL, STAGE3_URL (frozen images) on your
own ports.
"""
import pytest

from s4lib import (Api, PAYMENT_KEYS, STAGE1_URL, STAGE2_URL, STAGE3_URL, assert_error, batch,
                   iso_ns, item, new_key, ns, now_ns, refund, user)

USERS = [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 800),
         user("u_dee", "dee", 5000), user("u_op", "op", 0)]
URLS = {1: STAGE1_URL, 2: STAGE2_URL, 3: STAGE3_URL}


def past(s=5):
    return iso_ns(now_ns() - s * 10 ** 9)


def source(stage):
    a = Api(URLS[stage])
    try:
        a.call("GET", "/health")
    except Exception as exc:
        pytest.fail(f"stage-{stage} source not reachable at {URLS[stage]}: {exc}")
    return a


def populate(src, stage):
    fx = {"currency": "EUR", "minor_units": 2, "users": USERS, "payments": [], "requests": [],
          "settlement_operator_ids": ["u_op"]}
    if stage >= 2:
        fx["authorizations"] = []
    src.reset(fx)
    tok = {u["handle"]: src.login(u["email"]) for u in USERS}
    rec = {"tok": tok, "receipts": []}

    def write(path, who, body):
        key = new_key()
        r = src.call("POST", path, tok[who], key, body)
        assert r.status_code == 201, (path, r.text)
        rec["receipts"].append((path, who, key, body, r.json()))
        return r.json()

    rec["pay"] = write("/payments", "ada", {"to_handle": "bob", "amount": 1200})
    req = write("/requests", "bob", {"payer_handle": "ada", "amount": 400})
    rec["paid_req"] = write(f"/requests/{req['request_id']}/pay", "ada", {})
    rec["settle"] = write("/settlements", "op", {"transfers": [
        {"from_handle": "dee", "to_handle": "cy", "amount": 100},
        {"from_handle": "cy", "to_handle": "ada", "amount": 100}]})
    if stage >= 2:
        a = write("/authorizations", "ada", {"to_handle": "dee", "amount": 500})
        rec["cap"] = write(f"/authorizations/{a['authorization_id']}/capture", "dee",
                           {"amount": 300})
    if stage >= 3:
        rec["corr"] = write(f"/payments/{rec['pay']['payment_id']}/corrections", "ada",
                            {"expected_revision": 1, "amount": 1000,
                             "effective_at": past(), "reason": "stage 3 fix"})
    rec["me"] = {h: src.call("GET", "/me", t).json() for h, t in tok.items()}
    rec["export"] = src.export()
    return rec


@pytest.fixture(params=[1, 2, 3])
def upgraded(request, api):
    src = source(request.param)
    rec = populate(src, request.param)
    rec["stage"] = request.param
    r = api.import_(rec["export"])
    assert r.status_code == 204, r.text
    yield rec
    src.http.close()


def test_R4_UPG_1_memberships_revisions_balances(upgraded, api):
    t = upgraded["tok"]
    for h, tk in t.items():
        assert api.me(tk)["balance"] == upgraded["me"][h]["balance"]
    sid = upgraded["settle"]["settlement_id"]
    feed = {x["payment_id"]: x for x in api.call("GET", "/activity", t["cy"],
                                                params={"limit": 200}).json()["payments"]}
    for m in upgraded["settle"]["payments"]:
        assert feed[m["payment_id"]]["settlement_id"] == sid
    revs = api.revisions(t["ada"], upgraded["pay"]["payment_id"]).json()["revisions"]
    if upgraded["stage"] == 3:
        assert [x["amount"] for x in revs] == [1200, 1000]
        assert revs[1]["reason"] == "stage 3 fix" and revs[1]["correction_batch_id"] is None
        assert ns(revs[1]["recorded_at"]) == ns(upgraded["corr"]["recorded_at"])
    else:
        assert [x["amount"] for x in revs] == [1200]


def test_R4_UPG_4_RSH_8_old_receipts_replay_verbatim(upgraded, api):
    t = upgraded["tok"]
    for path, who, key, body, original in upgraded["receipts"]:
        r = api.call("POST", path, t[who], key, body)
        assert r.status_code == 200, (path, r.text)
        assert r.json() == original                    # no refund_of added to stored bodies
    for x in api.call("GET", "/activity", t["ada"], params={"limit": 200}).json()["payments"]:
        assert set(x) == PAYMENT_KEYS and x["refund_of"] is None


def test_R4_UPG_5_imported_settlement_batch_correctable(upgraded, api):
    t = upgraded["tok"]
    st = upgraded["settle"]
    a, b = (m["payment_id"] for m in st["payments"])
    r = batch(api, t["op"], [item(a, 1, 50, st["committed_at"]),
                             item(b, 1, 50, st["committed_at"])])
    assert r.status_code == 201, r.text
    assert_error(api.correct(t["dee"], a, 2, 40, past()), 422, "linked_payment_immutable")
    if upgraded["stage"] >= 2:
        assert_error(batch(api, t["op"], [item(upgraded["cap"]["payment_id"], 1, 0, past())]),
                     422, "linked_payment_immutable")
    f = refund(api, t["bob"], upgraded["pay"]["payment_id"], 100)
    assert f.status_code == 201 and f.json()["refund_of"] == upgraded["pay"]["payment_id"]


def test_R4_UPG_2_stage4_snapshots_round_trip(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    first = api.statement(tk["ada"], limit=2).json()
    snap = first["snapshot"]
    full = api.statement(tk["ada"], limit=200).json()["entries"]
    exported = api.export()
    api.reset(world.fx)
    assert_error(api.statement(tk["ada"], snapshot=snap), {401, 404},
                 {"unauthenticated", "not_found"})
    assert api.import_(exported).status_code == 204
    page = api.statement(tk["ada"], snapshot=snap, limit=200).json()     # restored (L10)
    assert page["entries"] == full
    assert page["opening_balance"] == first["opening_balance"]
    # later writes never change it
    api.correct(tk["ada"], p["payment_id"], 1, 10, past())
    assert api.statement(tk["ada"], snapshot=snap, limit=200).json()["entries"] == full
    # import MERGES (L12): a destination token minted before the import still pages after it
    api.reset(world.fx)
    ada = api.login("ada@example.com")
    other = api.statement(ada, limit=200).json()
    assert api.import_(exported).status_code == 204
    again = api.statement(ada, snapshot=other["snapshot"], limit=200).json()
    assert again["entries"] == other["entries"]
    assert api.statement(ada, snapshot=snap, limit=200).json()["entries"] == full

def test_R4_UPG_3_stage3_export_imports_without_snapshots(api):
    src = source(3)
    rec = populate(src, 3)
    src_snap = src.call("GET", "/statement", rec["tok"]["ada"]).json()["snapshot"]
    exported = src.export()
    assert api.import_(exported).status_code == 204
    # known limitation (D-74): frozen stage-3 exports carry no snapshots, nothing to merge
    r = api.statement(rec["tok"]["ada"], snapshot=src_snap)
    assert_error(r, 404, "not_found")
    src.http.close()
