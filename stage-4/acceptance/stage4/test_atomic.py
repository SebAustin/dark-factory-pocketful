"""Atomicity and concurrency of batches. Ledger R4-CONC.1/2/3, R4-BMNY.4."""
import threading

import pytest

from s4lib import (assert_error, batch, fingerprint, iso_ns, item, new_key, ns, now_ns, refund,
                   run_parallel)


def past(s=5):
    return iso_ns(now_ns() - s * 10 ** 9)


def settle(api, world, transfers):
    r = api.call("POST", "/settlements", world.tok["op"], new_key(), {"transfers": transfers})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- failure injected on the LAST item

def scenario(api, world, rule):
    """Three valid items plus a last item (or tail) that fails `rule`; returns (items, status,
    code, pids_to_watch)."""
    tk = world.tok
    good = [world.pay("dee", "ada", 100 + i) for i in range(3)]   # lowering them debits ada
    items = [item(p["payment_id"], 1, 50, past()) for p in good]
    watch = [(p["payment_id"], "ada") for p in good]
    if rule == "field":
        tail, st, code = [item(good[0]["payment_id"] + "x", 1, -1, past())], 422, "validation_failed"
    elif rule == "unknown":
        tail, st, code = [item("p_nope", 1, 0, past())], 404, "not_found"
    elif rule == "capture":
        a = api.call("POST", "/authorizations", tk["dee"], new_key(),
                     {"to_handle": "cy", "amount": 100}).json()
        c = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["cy"],
                     new_key(), {}).json()
        tail, st, code = [item(c["payment_id"], 1, 0, past())], 422, "linked_payment_immutable"
    elif rule == "refund":
        p = world.pay("dee", "cy", 300)
        f = refund(api, tk["cy"], p["payment_id"], 100).json()
        tail, st, code = [item(f["payment_id"], 1, 0, past())], 422, "linked_payment_immutable"
    elif rule == "stale":
        p = world.pay("dee", "cy", 300)
        api.correct(tk["dee"], p["payment_id"], 1, 250, past())
        tail, st, code = [item(p["payment_id"], 1, 0, past())], 409, "stale_revision"
    elif rule == "refund_exceeds":
        p = world.pay("dee", "cy", 300)
        refund(api, tk["cy"], p["payment_id"], 200)
        tail, st, code = [item(p["payment_id"], 1, 100, past())], 422, "refund_exceeds_payment"
    elif rule == "incomplete":
        s = settle(api, world, [{"from_handle": "dee", "to_handle": "cy", "amount": 10},
                                {"from_handle": "cy", "to_handle": "dee", "amount": 5}])
        tail, st, code = [item(s["payments"][0]["payment_id"], 1, 0, s["committed_at"])], 422, \
            "incomplete_settlement"
    elif rule == "instants":
        s = settle(api, world, [{"from_handle": "dee", "to_handle": "cy", "amount": 10},
                                {"from_handle": "cy", "to_handle": "dee", "amount": 5}])
        t = ns(s["committed_at"])
        tail = [item(s["payments"][0]["payment_id"], 1, 0, iso_ns(t)),
                item(s["payments"][1]["payment_id"], 1, 0, iso_ns(t + 1000))]
        st, code = 422, "validation_failed"
    elif rule == "insufficient":
        p = world.pay("cy", "dee", 100)
        tail, st, code = [item(p["payment_id"], 1, 10 ** 9, past())], 409, "insufficient_funds"
    elif rule == "historical":
        s = settle(api, world, [{"from_handle": "ada", "to_handle": "bob", "amount": 1000},
                                {"from_handle": "bob", "to_handle": "cy", "amount": 200}])
        world.pay("bob", "dee", api.me(tk["bob"])["balance"])   # bob spends everything
        world.pay("dee", "bob", 3300)                           # and is paid back later
        tail = [item(s["payments"][0]["payment_id"], 1, 0, s["committed_at"]),
                item(s["payments"][1]["payment_id"], 1, 200, s["committed_at"])]
        st, code = 409, "historical_overdraft"
    return items + tail, st, code, watch


RULES = ["field", "unknown", "capture", "refund", "stale", "refund_exceeds", "incomplete",
         "instants", "insufficient", "historical"]


@pytest.mark.parametrize("rule", RULES)
def test_R4_CONC_3_BMNY_4_failure_on_last_item_changes_nothing(world, api, rule):
    items, st, code, watch = scenario(api, world, rule)
    snap = api.statement(world.tok["ada"]).json()["snapshot"]
    before = fingerprint(api, world, pids=watch, snaps=[(world.tok["ada"], snap)])
    key = new_key()
    assert_error(batch(api, world.tok["op"], items, key), st, code)
    after = fingerprint(api, world, pids=watch, snaps=[(world.tok["ada"], snap)])
    assert after == before
    # the key was not claimed: the valid prefix succeeds with it
    ok = batch(api, world.tok["op"], items[:3], key)
    assert ok.status_code == 201, ok.text


# ---------------------------------------------------------------- races

def test_R4_CONC_1_single_vs_batch_vs_batch_race(world, api):
    tk = world.tok
    p = world.pay("ada", "bob", 1000)
    others = [world.pay("ada", "cy", 10 + i) for i in range(10)]

    def act(i):
        if i < 10:
            return ("single", api.correct(tk["ada"], p["payment_id"], 1, 900 - i, past()))
        o = others[i - 10]
        return ("batch", batch(api, tk["op"], [item(o["payment_id"], 1, 5, past()),
                                               item(p["payment_id"], 1, 800 - i, past())]))

    res = run_parallel(act, 20)
    wins = [(k, r) for k, r in res if r.status_code == 201]
    assert len(wins) == 1, [(k, r.status_code) for k, r in res]
    for k, r in res:
        if r.status_code != 201:
            assert_error(r, 409, "stale_revision")
    revs = api.revisions(tk["ada"], p["payment_id"]).json()["revisions"]
    assert [x["revision"] for x in revs] == [1, 2]
    # losing batches left their other payment untouched
    kind, win = wins[0]
    touched = {x["payment_id"] for x in win.json().get("revisions", [])}
    for o in others:
        n = len(api.revisions(tk["ada"], o["payment_id"]).json()["revisions"])
        assert n == (2 if o["payment_id"] in touched else 1)
    assert sum(api.me(t)["balance"] for t in tk.values()) == world.seeded_total


def test_R4_CONC_2_batch_atomic_under_50_way_load(world, api):
    tk = world.tok
    pairs = [(world.pay("ada", "bob", 20)["payment_id"], world.pay("ada", "bob", 30)["payment_id"])
             for _ in range(25)]
    stop = threading.Event()
    torn, sums = [], []

    def reader():
        while not stop.is_set():
            st = api.statement(tk["ada"], limit=200).json()
            ent = {e["payment"]["payment_id"]: e for e in st["entries"]}
            for x, y in pairs:
                ex, ey = ent.get(x), ent.get(y)
                # y is only ever corrected by the pair's batch: if y shows it, x must show the
                # same batch (a single correction of x alone is legitimate)
                if ey and ey["revision"] == 2 and (ex["revision"] != 2 or ex.get(
                        "correction_batch_id") != ey.get("correction_batch_id")):
                    torn.append((x, y, ex["revision"], ey["revision"]))

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for th in readers:
        th.start()

    def write(i):
        if i < 25:
            x, y = pairs[i]
            return batch(api, tk["op"], [item(x, 1, 10, past()), item(y, 1, 15, past())]).status_code
        # 25 conflicting singles on the same payments (expected revision 1)
        x, y = pairs[i - 25]
        return api.correct(tk["ada"], x, 1, 19, past()).status_code

    try:
        codes = run_parallel(write, 50, workers=50)
    finally:
        stop.set()
        for th in readers:
            th.join()
    assert all(c in (201, 409) for c in codes), codes
    assert not torn, torn[:5]
    assert sum(api.me(t)["balance"] for t in tk.values()) == world.seeded_total
    for i, (x, y) in enumerate(pairs):
        rx = api.revisions(tk["ada"], x).json()["revisions"]
        ry = api.revisions(tk["ada"], y).json()["revisions"]
        # either the batch won (both corrected by it) or the single won (x only)
        if len(ry) == 2:
            assert rx[-1]["correction_batch_id"] == ry[-1]["correction_batch_id"] is not None
        else:
            assert len(rx) == 2 and rx[-1]["correction_batch_id"] is None
