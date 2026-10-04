"""Historical holds. Ledger R3-HH."""
import time
from datetime import datetime, timedelta

from s3lib import UTC, US, base_fixture, iso, iso_ns, new_key, ns, now_ns, user


def authorize(api, tok, to, amount):
    r = api.call("POST", "/authorizations", tok, new_key(), {"to_handle": to, "amount": amount})
    assert r.status_code == 201, r.text
    return r.json()


def view(api, tok, T, K=None):
    params = {"as_of": T}
    if K:
        params["known_at"] = K
    m = api.me(tok, **params)
    return m["total"], m["held"], m["available"]


def test_R3_HH_1_HH_2_HH_3_nonfinal_then_final_capture(world, api):
    tk = world.tok
    a = authorize(api, tk["ada"], "bob", 2000)
    c1 = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                  new_key(), {"amount": 500, "final": False}).json()
    c2 = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                  new_key(), {"amount": 300}).json()
    tc, t1, t2 = ns(a["created_at"]), ns(c1["created_at"]), ns(c2["created_at"])
    assert view(api, tk["ada"], iso_ns(tc - US)) == (10000, 0, 10000)
    assert view(api, tk["ada"], iso_ns(tc)) == (10000, 2000, 8000)
    assert view(api, tk["ada"], iso_ns(t1 - US)) == (10000, 2000, 8000)
    assert view(api, tk["ada"], iso_ns(t1)) == (9500, 1500, 8000)
    assert view(api, tk["ada"], iso_ns(t2)) == (9200, 0, 9200)


def test_R3_HH_3_HH_5_HH_9_void_release_and_known_at(world, api):
    tk = world.tok
    a = authorize(api, tk["ada"], "bob", 2000)
    v = api.call("POST", f"/authorizations/{a['authorization_id']}/void", tk["ada"]).json()
    assert v["closed_at"] is not None
    tv = ns(v["closed_at"])
    assert view(api, tk["ada"], iso_ns(tv - US)) == (10000, 2000, 8000)
    assert view(api, tk["ada"], iso_ns(tv)) == (10000, 0, 10000)
    # known before the void: still held after the void instant
    assert view(api, tk["ada"], iso_ns(tv + 10 * US), iso_ns(tv - US)) == (10000, 2000, 8000)
    # known before the creation: nothing
    assert view(api, tk["ada"], iso_ns(tv), iso_ns(ns(a["created_at"]) - US)) == \
        (10000, 0, 10000)


def test_R3_HH_4_HH_6_HH_7_expiry_at_deadline(make_world, api):
    fx = base_fixture(authorization_ttl_seconds=2)
    w = make_world(fx)
    a = authorize(api, w.tok["ada"], "bob", 2000)
    te = ns(a["expires_at"])
    tc = ns(a["created_at"])
    # future as_of (before the deadline passes in real time): released at the deadline
    assert view(api, w.tok["ada"], iso_ns(te)) == (10000, 0, 10000)
    assert view(api, w.tok["ada"], iso_ns(te - US)) == (10000, 2000, 8000)
    # known right at creation: the deadline is known too
    assert view(api, w.tok["ada"], iso_ns(te + US), iso_ns(tc)) == (10000, 0, 10000)
    time.sleep(2.5)
    got = api.call("GET", "/authorizations", w.tok["ada"]).json()["authorizations"][0]
    assert got["status"] == "expired" and ns(got["closed_at"]) == te
    assert view(api, w.tok["ada"], iso_ns(te - US)) == (10000, 2000, 8000)


def test_R3_HH_8_known_at_only_uses_read_instant(world, api):
    a = authorize(api, world.tok["ada"], "bob", 2000)
    m = api.me(world.tok["ada"], known_at=iso_ns(now_ns() + 10 ** 9))
    assert (m["total"], m["held"], m["available"]) == (10000, 2000, 8000)
    m = api.me(world.tok["ada"], known_at=iso_ns(ns(a["created_at"]) - US))
    assert (m["held"], m["available"]) == (0, 10000)


def test_R3_HH_9_closed_at_values(world, api):
    tk = world.tok
    a = authorize(api, tk["ada"], "bob", 100)
    assert a["closed_at"] is None
    cap = api.call("POST", f"/authorizations/{a['authorization_id']}/capture", tk["bob"],
                   new_key(), {}).json()
    got = next(x for x in api.call("GET", "/authorizations", tk["ada"]).json()["authorizations"]
               if x["authorization_id"] == a["authorization_id"])
    assert ns(got["closed_at"]) == ns(cap["created_at"])


def test_R3_HH_11_seeded_holds_history(api):
    t_created = iso(datetime.now(UTC) - timedelta(hours=2))
    fut = iso(datetime.now(UTC) + timedelta(hours=2))
    past = iso(datetime.now(UTC) - timedelta(hours=1, minutes=5))
    fx = base_fixture(authorizations=[
        {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000,
         "status": "open", "expires_at": fut, "created_at": t_created},
        {"id": "a_open_r", "from_user_id": "u_dee", "to_user_id": "u_bob", "amount": 700,
         "status": "open", "expires_at": fut},
        {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 400,
         "status": "expired", "expires_at": past},
    ])
    before = now_ns()
    api.reset(fx)
    ada, dee = api.login("ada@example.com"), api.login("dee@example.com")
    m = api.me(ada, as_of=t_created)
    assert m["held"] == 1000
    assert api.me(ada, as_of=iso_ns(ns(t_created) - US))["held"] == 0
    # seeded open hold without created_at: created at reset
    assert api.me(dee, as_of=iso_ns(before - 10 ** 9))["held"] == 0
    assert api.me(dee)["held"] == 700
    exp = next(x for x in api.call("GET", "/authorizations", ada).json()["authorizations"]
               if x["authorization_id"] == "a_exp")
    assert exp["status"] == "expired" and ns(exp["closed_at"]) == ns(past)
    assert api.me(ada, as_of=iso_ns(ns(past) - US))["held"] == 1000   # a_exp never held
