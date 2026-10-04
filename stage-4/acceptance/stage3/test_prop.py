"""Property / differential tests against the analyst's reference model (D-48, D-51, D-53, D-55).

Ledger R3-INV.1/2/3, R3-ME.4/9, R3-ST.6/7/11, R3-KN.2/4, R3-REV.1, R3-HH model rows, R3-MNY.7.
"""
import random

import pytest

from s3lib import (NEG_INF, POS_INF, US, iso_ns, model_correction_verdict, new_key, ns, now_ns,
                   run_parallel)

FAR_PAST = "1970-01-01T00:00:00+00:00"
FAR_FUTURE = "2999-01-01T00:00:00+00:00"


def build_history(world, api, seed):
    rnd = random.Random(seed)
    tk, m = world.tok, world.model
    s1 = ns(world.fx["payments"][0]["created_at"])
    s2 = ns(world.fx["payments"][1]["created_at"])
    pays = [world.pay("ada", "bob", 1000), world.pay("bob", "cy", 700),
            world.pay("dee", "ada", 300), world.pay("cy", "dee", 200)]
    rid = api.call("POST", "/requests", tk["bob"], new_key(),
                   {"payer_handle": "ada", "amount": 400}).json()["request_id"]
    rp = api.call("POST", f"/requests/{rid}/pay", tk["ada"], new_key(), {}).json()
    m.add_payment(rp)
    st = api.call("POST", "/settlements", tk["op"], new_key(), {"transfers": [
        {"from_handle": "dee", "to_handle": "cy", "amount": 100},
        {"from_handle": "cy", "to_handle": "ada", "amount": 100}]}).json()
    for p in st["payments"]:
        m.add_payment(p)
    a1 = api.call("POST", "/authorizations", tk["ada"], new_key(),
                  {"to_handle": "bob", "amount": 2000}).json()
    m.add_auth(a1)
    c1 = api.call("POST", f"/authorizations/{a1['authorization_id']}/capture", tk["bob"],
                  new_key(), {"amount": 500, "final": False}).json()
    m.capture_event(a1["authorization_id"], c1, False)
    v1 = api.call("POST", f"/authorizations/{a1['authorization_id']}/void", tk["ada"]).json()
    m.void_event(a1["authorization_id"], v1["closed_at"])
    a2 = api.call("POST", "/authorizations", tk["dee"], new_key(),
                  {"to_handle": "cy", "amount": 800}).json()
    m.add_auth(a2)
    c2 = api.call("POST", f"/authorizations/{a2['authorization_id']}/capture", tk["cy"],
                  new_key(), {"amount": 300}).json()
    m.capture_event(a2["authorization_id"], c2, True)
    a3 = api.call("POST", "/authorizations", tk["bob"], new_key(),
                  {"to_handle": "dee", "amount": 600}).json()       # stays open
    m.add_auth(a3)
    # corrections: backdated, reversal, same amount earlier, increase; random extra ones
    mid = (s1 + s2) // 2
    plans = [(pays[0], "ada", 400, mid), (pays[1], "bob", 0, ns(pays[1]["created_at"])),
             (pays[2], "dee", 300, mid + 7 * US), (rp, "ada", 450, ns(rp["created_at"]) - US)]
    for _ in range(4):
        p = rnd.choice(pays)
        sender = {"u_ada": "ada", "u_bob": "bob", "u_dee": "dee", "u_cy": "cy"}[p["from_user_id"]]
        plans.append((p, sender, rnd.randint(0, 1500), rnd.randint(s1 - 10 ** 9, now_ns() - 10 ** 6)))
    verdicts = []
    for p, sender, amount, eff in plans:
        pid = p["payment_id"]
        cur = max(m.payments[pid]["revs"], key=lambda r: r[3])
        expect = model_correction_verdict(m, pid, amount, eff, now_ns())
        r = world.api.correct(tk[sender], pid, cur[0], amount, iso_ns(eff))
        if r.status_code == 201:
            m.add_revision(r.json())
            got = None
        else:
            assert r.status_code == 409, r.text
            got = r.json()["error"]["code"]
        verdicts.append((pid, amount, eff, expect, got))
    return verdicts


@pytest.fixture(params=[1, 2])
def history(request, world, api):
    verdicts = build_history(world, api, request.param)
    return world, verdicts


def test_R3_MNY_4_MNY_8_correction_verdicts_match_model(history):
    world, verdicts = history
    wrong = [v for v in verdicts if v[3] != v[4]]
    # a verdict can only differ if it sits on the knife edge of "now"; none of ours do
    assert not wrong, wrong


def grid_T(model):
    pts = model.boundaries()
    out = {ns(FAR_PAST), ns(FAR_FUTURE)}
    for b in pts:
        out |= {b - US, b, b + US}
    return sorted(out)


def test_R3_INV_1_INV_2_ME_4_ME_9_HH_model_every_view(history, api):
    world, _ = history
    m = world.model
    users = list(world.tok)
    Ts = grid_T(m)
    Ks = [None] + sorted({k for r in m.recorded_points() for k in (r - US, r)})
    mismatches, sums = [], []
    for K in Ks:
        Tset = Ts if K is None else Ts[::3]
        for T in Tset:
            total_sum = 0
            for h in users:
                params = {"as_of": iso_ns(T)}
                if K is not None:
                    params["known_at"] = iso_ns(K)
                got = api.me(world.tok[h], **params)
                want = m.view(world.uid[h], T, POS_INF if K is None else K)
                for f in ("balance", "total", "held", "available"):
                    if got[f] != want[f]:
                        mismatches.append((h, iso_ns(T), K and iso_ns(K), f, got[f], want[f]))
                assert got["total"] >= 0 and got["available"] >= 0 and got["held"] >= 0
                assert got["balance"] == got["total"]
                assert got["available"] == got["total"] - got["held"]
                total_sum += got["total"]
            if total_sum != world.seeded_total:
                sums.append((iso_ns(T), K, total_sum))
    assert not mismatches, mismatches[:10]
    assert not sums, sums[:10]


def test_R3_ST_6_ST_7_ST_11_KN_2_statements_match_model(history, api):
    world, _ = history
    m = world.model
    pts = [ns(FAR_PAST)] + m.boundaries() + [ns(FAR_FUTURE)]
    rnd = random.Random(5)
    Ks = [None] + rnd.sample(m.recorded_points(), k=min(5, len(m.recorded_points())))
    bad = []
    for h in ("ada", "bob", "cy", "dee"):
        uid = world.uid[h]
        for _ in range(12):
            a, b = sorted(rnd.sample(pts, 2))
            for K in Ks:
                params = {"from": iso_ns(a), "to": iso_ns(b)}
                if K is not None:
                    params["known_at"] = iso_ns(K)
                first, entries = api.statement_all(world.tok[h], limit=4, **params)
                want = m.statement(uid, a, b, POS_INF if K is None else K)
                got = {"opening_balance": first["opening_balance"],
                       "closing_balance": first["closing_balance"],
                       "entries": [{"payment_id": e["payment"]["payment_id"], "delta": e["delta"],
                                    "balance_after": e["balance_after"],
                                    "revision": e["revision"], "amount": e["payment"]["amount"]}
                                   for e in entries]}
                if got != want:
                    bad.append((h, params, got, want))
                assert first["opening_balance"] + sum(e["delta"] for e in entries) == \
                    first["closing_balance"]
    assert not bad, bad[:3]


def test_R3_INV_3_current_equals_views(history, api):
    world, _ = history
    for h, t in world.tok.items():
        cur = api.me(t)
        assert api.me(t, as_of=FAR_FUTURE)["balance"] == cur["balance"]
        st = api.statement(t, limit=200).json()
        assert st["closing_balance"] == cur["balance"]
        assert cur["balance"] == world.model.view(world.uid[h], now_ns(), POS_INF)["total"]


def test_R3_INV_4_concurrent_mixed_serialisable(world, api):
    tk = world.tok
    ps = [world.pay("ada", "bob", 100) for _ in range(5)]

    def work(i):
        k = i % 4
        if k == 0:
            return api.pay(tk["ada"], "dee", 10).status_code
        if k == 1:
            p = ps[i % 5]
            return api.correct(tk["ada"], p["payment_id"], 1, 50,
                               iso_ns(now_ns() - 10 ** 9)).status_code
        if k == 2:
            return api.statement(tk["ada"], limit=3).status_code
        return api.call("GET", "/me", tk["bob"], params={"as_of": iso_ns(now_ns())}).status_code

    codes = run_parallel(work, 80, workers=30)
    assert all(c < 500 for c in codes), codes
    total = sum(api.me(t)["balance"] for t in tk.values())
    assert total == world.seeded_total
    for p in ps:
        revs = api.revisions(tk["ada"], p["payment_id"]).json()["revisions"]
        assert len(revs) <= 2
