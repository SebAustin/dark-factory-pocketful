"""Upgrades over populated state: real exports from the frozen stage-1 and stage-2 images.

Ledger R3-UPG, R3-SET.3/4 on imported data, R3-HH.9 for imported holds.
Needs STAGE1_URL (frozen stage-1 image) and STAGE2_URL (frozen stage-2 image) on your own ports.
"""
import pytest

from s3lib import (Api, STAGE1_URL, STAGE2_URL, US, assert_error, iso_ns, new_key, ns, now_ns,
                   user)

USERS = [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500), user("u_cy", "cy", 800),
         user("u_dee", "dee", 5000), user("u_op", "op", 0)]
OPENING = {"u_ada": 10000, "u_bob": 2500, "u_cy": 800, "u_dee": 5000, "u_op": 0}


def source(url):
    a = Api(url)
    try:
        a.call("GET", "/health")
    except Exception as exc:
        pytest.fail(f"source service not reachable at {url}: {exc}")
    return a


def populate(src, stage):
    fx = {"currency": "EUR", "minor_units": 2, "users": USERS, "payments": [], "requests": [],
          "settlement_operator_ids": ["u_op"]}
    if stage == 2:
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

    rec["pay"] = write("/payments", "ada", {"to_handle": "bob", "amount": 1200, "note": "a"})
    write("/payments", "bob", {"to_handle": "cy", "amount": 300, "visibility": "private"})
    req = write("/requests", "bob", {"payer_handle": "ada", "amount": 400})
    rec["paid_req"] = write(f"/requests/{req['request_id']}/pay", "ada", {})
    rec["pending"] = write("/requests", "cy", {"payer_handle": "dee", "amount": 250})
    write("/splits", "dee", {"amount": 900, "participant_handles": ["dee", "ada", "cy"]})
    rec["settle"] = write("/settlements", "op", {"transfers": [
        {"from_handle": "dee", "to_handle": "cy", "amount": 100},
        {"from_handle": "cy", "to_handle": "ada", "amount": 100}]})
    if stage == 2:
        a1 = write("/authorizations", "ada", {"to_handle": "dee", "amount": 1000})
        rec["cap1"] = write(f"/authorizations/{a1['authorization_id']}/capture", "dee",
                            {"amount": 300, "final": False})
        rec["open_auth"] = a1
        a2 = write("/authorizations", "dee", {"to_handle": "bob", "amount": 500})
        rec["cap2"] = write(f"/authorizations/{a2['authorization_id']}/capture", "bob",
                            {"amount": 200})
        rec["closed_auth"] = a2
        a3 = write("/authorizations", "bob", {"to_handle": "ada", "amount": 50})
        src.call("POST", f"/authorizations/{a3['authorization_id']}/void", tok["bob"])
        rec["void_auth"] = a3
    rec["me"] = {h: src.me(t) for h, t in tok.items()}
    feeds = {}
    for h, t in tok.items():
        for p in src.call("GET", "/activity", t, params={"limit": 200}).json()["payments"]:
            feeds[p["payment_id"]] = p
    rec["payments"] = feeds
    rec["export"] = src.export()
    return rec


@pytest.fixture(params=[1, 2])
def upgraded(request, api):
    src = source(STAGE1_URL if request.param == 1 else STAGE2_URL)
    rec = populate(src, request.param)
    rec["stage"] = request.param
    r = api.import_(rec["export"])
    assert r.status_code == 204, r.text
    yield rec
    src.http.close()


def test_R3_UPG_1_UPG_2_balances_and_holds_accounted(upgraded, api):
    for h, t in upgraded["tok"].items():          # source tokens still work
        m = api.me(t)
        src = upgraded["me"][h]
        for f in ("balance", "total", "available", "held"):
            if f in src:
                assert m[f] == src[f], (h, f, m, src)
        assert m["balance"] == src["balance"]
    assert sum(api.me(t)["balance"] for t in upgraded["tok"].values()) == sum(OPENING.values())


def test_R3_UPG_3_revision1_and_opening(upgraded, api):
    t = upgraded["tok"]
    for pid, p in upgraded["payments"].items():
        party = next(h for h, u in (("ada", "u_ada"), ("bob", "u_bob"), ("cy", "u_cy"),
                                    ("dee", "u_dee"), ("op", "u_op"))
                     if u in (p["from_user_id"], p["to_user_id"]))
        r = api.revisions(t[party], pid)
        assert r.status_code == 200, (pid, r.text)
        revs = r.json()["revisions"]
        assert len(revs) == 1 and revs[0]["amount"] == p["amount"] and revs[0]["reason"] == ""
        assert ns(revs[0]["effective_at"]) == ns(revs[0]["recorded_at"]) == ns(p["created_at"])
    for h, uid in (("ada", "u_ada"), ("bob", "u_bob"), ("cy", "u_cy"), ("dee", "u_dee")):
        assert api.me(t[h], as_of="1970-01-01T00:00:00Z")["balance"] == OPENING[uid]
        st = api.statement(t[h], limit=200).json()
        assert st["opening_balance"] == OPENING[uid]
        assert st["closing_balance"] == upgraded["me"][h]["balance"]
        mine = {pid for pid, p in upgraded["payments"].items()
                if uid in (p["from_user_id"], p["to_user_id"])}
        assert {e["payment"]["payment_id"] for e in st["entries"]} == mine


def test_R3_UPG_4_receipts_tokens_requests_corrections(upgraded, api):
    t = upgraded["tok"]
    for path, who, key, body, original in upgraded["receipts"]:
        r = api.call("POST", path, t[who], key, body)
        assert r.status_code == 200, (path, r.text)
        assert r.json() == original
    rid = upgraded["pending"]["request_id"]
    assert api.call("POST", f"/requests/{rid}/pay", t["dee"], new_key(), {}).status_code == 201
    pay = upgraded["pay"]
    r = api.correct(t["ada"], pay["payment_id"], 1, 1000, iso_ns(now_ns() - 10 ** 9))
    assert r.status_code == 201, r.text
    for m in upgraded["settle"]["payments"]:
        sender = {"u_dee": "dee", "u_cy": "cy"}[m["from_user_id"]]
        assert_error(api.correct(t[sender], m["payment_id"], 1, 1, iso_ns(now_ns() - 10 ** 9)),
                     422, "linked_payment_immutable")
    if upgraded["stage"] == 2:
        assert_error(api.correct(t["ada"], upgraded["cap1"]["payment_id"], 1, 1,
                                 iso_ns(now_ns() - 10 ** 9)), 422, "linked_payment_immutable")


@pytest.fixture
def upgraded2(api):
    src = source(STAGE2_URL)
    rec = populate(src, 2)
    assert api.import_(rec["export"]).status_code == 204
    yield rec
    src.http.close()


def test_R3_UPG_2_HH_9_imported_hold_history(upgraded2, api):
    upgraded = upgraded2
    t = upgraded["tok"]
    auths = {a["authorization_id"]: a for a in api.call(
        "GET", "/authorizations", t["ada"], params={"limit": 200}).json()["authorizations"]}
    auths.update({a["authorization_id"]: a for a in api.call(
        "GET", "/authorizations", t["bob"], params={"limit": 200}).json()["authorizations"]})
    oa = auths[upgraded["open_auth"]["authorization_id"]]
    assert oa["status"] == "open" and oa["closed_at"] is None
    ca = auths[upgraded["closed_auth"]["authorization_id"]]
    assert ns(ca["closed_at"]) == ns(upgraded["cap2"]["created_at"])
    va = auths[upgraded["void_auth"]["authorization_id"]]
    assert va["status"] == "voided" and ns(va["closed_at"]) == ns(va["created_at"])  # D-52
    # ada's hold over time: 1000 from creation, 700 after the non-final capture
    tc = ns(upgraded["open_auth"]["created_at"])
    t1 = ns(upgraded["cap1"]["created_at"])
    # stage-2 instants have whole seconds: creation and capture may share one instant
    assert api.me(t["ada"], as_of=iso_ns(tc))["held"] == (1000 if t1 > tc else 700)
    assert api.me(t["ada"], as_of=iso_ns(t1))["held"] == 700
    assert api.me(t["ada"], as_of=iso_ns(tc - US))["held"] == 0


def test_R3_UPG_6_session_rule_by_source_stage(api):
    for url, stage in ((STAGE1_URL, 1), (STAGE2_URL, 2)):
        src = source(url)
        rec = populate(src, stage)
        fx = {"currency": "EUR", "minor_units": 2, "users": USERS, "payments": [],
              "requests": [], "authorizations": [], "settlement_operator_ids": ["u_op"]}
        api.reset(fx)
        dest = api.login("ada@example.com")
        assert api.import_(rec["export"]).status_code == 204
        assert api.me(dest)["user_id"] == "u_ada", stage    # L5 extended (D-52)
        src.http.close()
    # a stage-3 export is pure replacement
    exported = api.export()
    late = api.login("bob@example.com")
    assert api.import_(exported).status_code == 204
    assert_error(api.call("GET", "/me", late), 401, "unauthenticated")


def test_R3_UPG_5_stage3_round_trip(world, api):
    p = world.pay("ada", "bob", 1000)
    r = world.correct("ada", p["payment_id"], 1, 600, iso_ns(now_ns() - 10 ** 9))
    assert r.status_code == 201
    snap = api.statement(world.tok["ada"]).json()["snapshot"]
    views = {h: (api.me(t), api.statement(t, limit=200).json()["entries"],
                 api.me(t, as_of=iso_ns(ns(p["created_at"])), known_at=iso_ns(
                     ns(r.json()["recorded_at"]) - US)))
             for h, t in world.tok.items()}
    revs = api.revisions(world.tok["ada"], p["payment_id"]).json()
    exported = api.export()
    api.reset(world.fx)
    assert api.import_(exported).status_code == 204
    for h, t in world.tok.items():
        me, entries, hist = views[h]
        assert api.me(t) == me
        assert api.statement(t, limit=200).json()["entries"] == entries
        assert api.me(t, as_of=iso_ns(ns(p["created_at"])), known_at=iso_ns(
            ns(r.json()["recorded_at"]) - US)) == hist
    assert api.revisions(world.tok["ada"], p["payment_id"]).json() == revs
    # stage 4 (L10, decision D-75): the export carries the snapshot and the import restores it
    assert api.statement(world.tok["ada"], snapshot=snap).status_code == 200
