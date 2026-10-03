"""§6 authentication, §4 handles. Ledger R-4.5, R-4.8-4.10, R-6.x, R-5.5."""
import time

import pytest

from conftest import PASSWORD, assert_error, new_key, run_parallel


def signup(api, email, password="longenough", display_name="New"):
    return api.post("/auth/signup", json={"email": email, "password": password,
                                          "display_name": display_name})


def test_R6_1_signup_201_shape_token_works(world, api):
    r = signup(api, "nina@example.com", display_name="Nina")
    assert r.status_code == 201
    body = r.json()
    assert set(body) >= {"user_id", "display_name", "token"}
    assert body["display_name"] == "Nina"
    me = api.me(body["token"])
    assert me["user_id"] == body["user_id"]
    assert me["handle"] == "nina"
    assert me["display_name"] == "Nina"


def test_R6_2_login_200_shape_token_works(world, api):
    uid = signup(api, "omar@example.com", password="omar-pass-1", display_name="Omar").json()[
        "user_id"]
    r = api.post("/auth/login", json={"email": "omar@example.com", "password": "omar-pass-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == uid
    assert body["display_name"] == "Omar"
    assert api.me(body["token"])["user_id"] == uid


def test_R4_10_signup_balance_zero_can_receive_and_be_asked(world, api):
    tok = signup(api, "pia@example.com").json()["token"]
    me = api.me(tok)
    assert me["balance"] == 0
    assert (me["currency"], me["minor_units"]) == ("EUR", 2)
    assert api.pay(world.tok["ada"], "pia", 250).status_code == 201
    assert api.balance(tok) == 250
    r = api.request(world.tok["bob"], "pia", 9999)
    assert r.status_code == 201
    assert r.json()["status"] == "pending"


def test_R6_3_signup_email_taken_409(world, api):
    assert_error(signup(api, "ada@example.com"), 409, "email_taken")
    assert signup(api, "quinn@example.com").status_code == 201
    assert_error(signup(api, "quinn@example.com"), 409, "email_taken")


def test_R6_4_password_length_7_422_8_ok(world, api):
    assert_error(signup(api, "rae@example.com", password="1234567"), 422, "validation_failed")
    assert signup(api, "rae@example.com", password="12345678").status_code == 201


@pytest.mark.parametrize("email", ["ada", "@example.com", "sam@", ""])
def test_R6_5_email_format_422(world, api, email):
    assert_error(signup(api, email), 422, "validation_failed")


def test_R5_9_signup_missing_fields_422(world, api):
    for body in ({"password": "longenough", "display_name": "X"},
                 {"email": "tia@example.com", "display_name": "X"},
                 {"email": "tia@example.com", "password": "longenough"}):
        assert_error(api.post("/auth/signup", json=body), 422, "validation_failed")


def test_R5_3_signup_wrong_type_400(world, api):
    r = api.post("/auth/signup", json={"email": 5, "password": "longenough",
                                       "display_name": "X"})
    assert_error(r, 400, "malformed_request")


def test_R6_6_login_wrong_password_or_unknown_email_401(world, api):
    r = api.post("/auth/login", json={"email": "ada@example.com", "password": "wrong horse"})
    assert_error(r, 401, "unauthenticated")
    r = api.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert_error(r, 401, "unauthenticated")


def test_R6_7_R4_9_signup_handle_collision_409(world, api):
    # "ada@other.org" derives handle "ada", already seeded
    assert_error(signup(api, "ada@other.org", password="other-pass"), 409, "handle_taken")
    r = api.post("/auth/login", json={"email": "ada@other.org", "password": "other-pass"})
    assert_error(r, 401, "unauthenticated")
    # "Ada.B@x" -> "ada_b": free
    assert signup(api, "Ada.B@x.org").status_code == 201
    # derived collision between two signups
    assert signup(api, "uma@one.org").status_code == 201
    assert_error(signup(api, "UMA@two.org"), 409, "handle_taken")


@pytest.mark.parametrize("email,handle", [
    ("Ada.Lovelace+x@example.com", "ada_lovelace_x"),
    ("abcdefghijklmnopqrstuvwxy@example.com", "abcdefghijklmnopqrst"),
    ("jérôme@example.com", "j_r_me"),
    ("Mixed-Case_9@example.com", "mixed_case_9"),
    ("a.b.c.d.e.f.g.h.i.j.k.l@example.com", "a_b_c_d_e_f_g_h_i_j_"),
])
def test_R4_8_derived_handle_rules(world, api, email, handle):
    r = signup(api, email)
    assert r.status_code == 201, r.text
    assert api.me(r.json()["token"])["handle"] == handle


def test_R4_5_me_handle_stable(world, api):
    tok = signup(api, "vic@example.com").json()["token"]
    first = api.me(tok)["handle"]
    api.pay(world.tok["ada"], "vic", 10)
    second_token = api.login("vic@example.com", "longenough")
    assert api.me(second_token)["handle"] == first == "vic"


def test_R6_10_multiple_tokens_all_valid(world, api):
    t1 = signup(api, "wes@example.com").json()["token"]
    t2 = api.login("wes@example.com", "longenough")
    t3 = api.login("wes@example.com", "longenough")
    assert len({t1, t2, t3}) >= 1
    for t in (t1, t2, t3):
        assert api.me(t)["handle"] == "wes"


AUTHED = [
    ("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
    ("POST", "/payments"), ("POST", "/requests"), ("POST", "/requests/rq_x/pay"),
    ("POST", "/requests/rq_x/decline"), ("POST", "/requests/rq_x/cancel"),
    ("POST", "/splits"), ("POST", "/settlements"),
]


@pytest.mark.parametrize("method,path", AUTHED)
@pytest.mark.parametrize("authz", [None, "Token abc", "Bearer", "Bearer not-a-real-token",
                                   "abc"])
def test_R5_5_R6_8_401_missing_malformed_unknown_token(world, api, method, path, authz):
    headers = {} if authz is None else {"Authorization": authz}
    r = api.call(method, path, headers=headers, key=new_key(),
                 json={} if method == "POST" else None)
    assert_error(r, 401, "unauthenticated")


def test_R2_9_50_concurrent_logins_within_5s(world, api):
    def login(_):
        t0 = time.monotonic()
        r = api.post("/auth/login", json={"email": "dee@example.com", "password": PASSWORD})
        return r.status_code, time.monotonic() - t0

    results = run_parallel(login, 50)
    assert all(s == 200 for s, _ in results), results
    assert max(d for _, d in results) < 5.0
