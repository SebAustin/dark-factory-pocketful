"""§5 errors, envelope, hostile inputs, cross-cutting precedence. Ledger R-5.x, R-X.1, R-X.2."""
import pytest

from conftest import assert_error, new_key

WRITE_PATHS = ["/payments", "/requests", "/splits"]


@pytest.mark.parametrize("path", WRITE_PATHS + ["/auth/signup", "/auth/login"])
def test_R5_3_unparseable_body_400(world, api, path):
    for raw in (b"{", b"not json", b'{"amount": 1,}', b"\xff\xfe\x00{"):
        r = api.call("POST", path, world.tok["ada"], new_key(), content=raw)
        assert_error(r, 400, "malformed_request")


@pytest.mark.parametrize("path", WRITE_PATHS)
@pytest.mark.parametrize("raw", [b"[]", b"5", b'"x"', b"null", b"true"])
def test_R5_3_non_object_body_400(world, api, path, raw):
    r = api.call("POST", path, world.tok["ada"], new_key(), content=raw)
    assert_error(r, 400, "malformed_request")


def test_R5_15_valid_type_bad_value_never_400(world, api):
    t = world.tok["ada"]
    for body in ({"to_handle": "bob", "amount": 0}, {"to_handle": "bob", "amount": 5,
                                                     "note": "x" * 201},
                 {"to_handle": "bob", "amount": 5, "visibility": "nope"}):
        assert_error(api.post("/payments", t, new_key(), body), 422, "validation_failed")


def test_R5_19_hostile_bodies_no_5xx(world, api):
    t = world.tok["ada"]
    bodies = [
        b"", b"\x00", b"\xc3\x28", b'{"to_handle":"bob","amount":1e400}',
        b'{"to_handle":"bob","amount":' + b"9" * 20000 + b"}",
        b'{"to_handle":"bob","amount":NaN}', b'{"to_handle":"bob","amount":Infinity}',
        b'{"to_handle":"bob","amount":5,"note":"' + b"x" * 300000 + b'"}',
        b'{"to_handle":"\\ud800","amount":5}',
    ]
    for raw in bodies:
        for path in ("/payments", "/requests", "/splits", "/auth/signup", "/_test/import"):
            r = api.call("POST", path, t, new_key(), content=raw)
            assert r.status_code < 500, (path, raw[:40], r.status_code, r.text[:200])
            assert r.status_code >= 400
            assert_error(r, r.status_code)


def test_R5_19_unknown_route_not_5xx(world, api):
    r = api.get("/nope", world.tok["ada"])
    assert 400 <= r.status_code < 500
    assert_error(r, r.status_code)


def test_RX_2_validation_before_not_found(world, api):
    r = api.pay(world.tok["ada"], "nobody", 0)
    assert_error(r, 422, "validation_failed")
    r = api.request(world.tok["ada"], "nobody", -5)
    assert_error(r, 422, "validation_failed")


def test_RX_1_precedence_matrix(world, api):
    t = world.tok["ada"]
    # 401 beats everything (no token, no key, bad body)
    r = api.call("POST", "/payments", content=b"{bad")
    assert_error(r, 401, "unauthenticated")
    # bad body + missing key: both 400; either code acceptable (spec does not order them)
    r = api.call("POST", "/payments", t, content=b"{bad")
    assert_error(r, 400, {"malformed_request", "missing_idempotency_key"})
    # missing key beats field validation
    r = api.post("/payments", t, None, {"to_handle": "bob", "amount": 0})
    assert_error(r, 400, "missing_idempotency_key")
    # key too long beats field validation
    r = api.post("/payments", t, "k" * 256, {"to_handle": "nobody", "amount": 5})
    assert_error(r, 422, "validation_failed")
    # self_payment needs no lookup; validation of amount first
    r = api.pay(t, "ada", 0)
    assert_error(r, 422, "validation_failed")
    # insufficient funds is last: a short sender with a bad note gets 422
    r = api.pay(world.tok["cy"], "ada", 5, note="x" * 201)
    assert_error(r, 422, "validation_failed")
    r = api.pay(world.tok["cy"], "nobody", 5)
    assert_error(r, 404, "not_found")
