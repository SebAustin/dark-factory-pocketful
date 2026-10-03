"""§1 invariants under concurrency, §2 limits. Ledger R-1.5-1.8, R-2.8/2.9, R-5.19, R-9.11."""
import random
import time

from conftest import base_fixture, new_key, run_parallel, user


def test_R1_7_concurrent_overspend_one_wins(make_world, api):
    w = make_world(users=[user("u_a", "aa", 1000), user("u_b", "bb", 0), user("u_c", "cc", 0)])
    for round_ in range(5):
        res = run_parallel(lambda i: api.pay(w.tok["aa"], "bb" if i % 2 else "cc", 1000), 30)
        codes = [r.status_code for r in res]
        assert all(c in (201, 409) for c in codes), codes
        if round_ == 0:
            assert codes.count(201) == 1, codes
        else:
            assert codes.count(201) == 0, codes
    assert w.balances() == {"aa": 0, "bb": 1000, "cc": 0} or \
        w.balances() == {"aa": 0, "bb": 0, "cc": 1000}


def test_R1_7_crossing_payments_never_negative(make_world, api):
    w = make_world(users=[user("u_a", "aa", 100), user("u_b", "bb", 100)])
    observed = []

    def work(i):
        src, dst = ("aa", "bb") if i % 2 else ("bb", "aa")
        r = api.pay(w.tok[src], dst, 60)
        observed.append(api.balance(w.tok[src]))
        return r.status_code

    codes = run_parallel(work, 40)
    assert all(c in (201, 409) for c in codes), codes
    assert min(observed) >= 0
    w.assert_invariants()


def test_R1_8_concurrent_pay_distinct_keys_one_payment(world, api):
    for _ in range(5):
        rid = api.request(world.tok["bob"], "ada", 100).json()["request_id"]
        res = run_parallel(lambda i: api.pay_request(world.tok["ada"], rid), 20)
        codes = [r.status_code for r in res]
        assert codes.count(201) == 1, codes
        assert all(c in (201, 409) for c in codes), codes
        assert {r.json()["error"]["code"] for r in res if r.status_code == 409} <= \
            {"request_not_pending"}
    assert world.balances()["ada"] == 10000 - 500
    world.assert_invariants()


def test_R1_8_pay_vs_cancel_race_single_outcome(world, api):
    for _ in range(10):
        rid = api.request(world.tok["bob"], "ada", 10).json()["request_id"]

        def act(i):
            if i % 2:
                return api.pay_request(world.tok["ada"], rid).status_code
            return api.post(f"/requests/{rid}/cancel", world.tok["bob"]).status_code

        run_parallel(act, 8)
        status = next(q["status"] for q in api.requests_list(world.tok["bob"])["requests"]
                      if q["request_id"] == rid)
        assert status in ("paid", "cancelled")
    paid = [q for q in api.requests_list(world.tok["bob"], limit=200)["requests"]
            if q["status"] == "paid"]
    assert world.balances()["bob"] == 2500 + 10 * len(paid)
    world.assert_invariants()


def test_R1_6_sum_conserved_concurrent_mixed_load(make_world, api):
    handles = [f"w{i}" for i in range(8)]
    w = make_world(base_fixture(users=[user(f"u_{h}", h, 1000) for h in handles]))
    rnd = random.Random(7)
    plan = [(rnd.choice(handles), rnd.choice(handles), rnd.randint(1, 400)) for _ in range(200)]

    def work(i):
        src, dst, amt = plan[i]
        if src == dst:
            return api.request(w.tok[src], handles[(handles.index(src) + 1) % 8], amt).status_code
        return api.pay(w.tok[src], dst, amt).status_code

    codes = run_parallel(work, 200, workers=50)
    assert all(c < 500 for c in codes), codes
    w.assert_invariants()


def test_R9_11_sum_conserved_after_splits_paid(world, api):
    for amount in (1000, 1, 10, 999, 7):
        s = api.post("/splits", world.tok["ada"], new_key(),
                     {"amount": amount, "participant_handles": ["bob", "ada", "dee"]}).json()
        for q in s["requests"]:
            r = api.pay_request(world.tok[q["payer_handle"]], q["request_id"])
            assert r.status_code == 201
    world.assert_invariants()


def test_R2_8_R2_9_R5_19_50_in_flight_no_5xx_within_timeout(world, api):
    def work(i):
        t0 = time.monotonic()
        kind = i % 5
        if kind == 0:
            r = api.pay(world.tok["ada"], "bob", 1)
        elif kind == 1:
            r = api.request(world.tok["bob"], "cy", 1)
        elif kind == 2:
            r = api.get("/activity", world.tok["cy"])
        elif kind == 3:
            r = api.get("/me", world.tok["dee"])
        else:
            r = api.post("/splits", world.tok["dee"], new_key(),
                         {"amount": 9, "participant_handles": ["ada", "bob"]})
        return r.status_code, time.monotonic() - t0

    res = run_parallel(work, 250, workers=50)
    assert all(code < 500 for code, _ in res), res
    assert max(d for _, d in res) < 5.0
    world.assert_invariants()
