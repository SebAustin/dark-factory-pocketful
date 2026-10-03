"""S1.AH hidden-requirement sweep: gaps found by reading the code against the ledger.

Ledger R-5.14, R-5.17, R-5.19, R-4.5, R-6.5, D-10.
"""
import pytest

from conftest import CONTROL_TIMEOUT, assert_error, base_fixture


@pytest.mark.parametrize("path", ["/activity", "/requests"])
@pytest.mark.parametrize("param", ["limit", "offset"])
@pytest.mark.parametrize("bad", ["4\n", "0\n", "\n4"])
def test_R5_14_query_int_with_newline_422(world, api, path, param, bad):
    # "written as plain decimal digits": a trailing/leading newline is not a digit
    assert_error(api.get(path, world.tok["ada"], params={param: bad}), 422, "validation_failed")


@pytest.mark.parametrize("path", ["/activity", "/requests"])
@pytest.mark.parametrize("param", ["limit", "offset"])
def test_R5_19_R5_17_query_int_5000_digits_422(world, api, path, param):
    r = api.get(path, world.tok["ada"], params={param: "1" * 5000})
    assert_error(r, 422, "validation_failed")


def test_R4_5_fixture_handle_with_newline_422(api):
    fx = base_fixture()
    fx["users"][1]["handle"] = "bob\n"
    r = api.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
    assert_error(r, 422, "validation_failed")


@pytest.mark.parametrize("email", ["nl@example.org\n", "\nnl@example.org", "n l@example.org"])
def test_R6_5_email_with_whitespace_422(world, api, email):
    r = api.post("/auth/signup", json={"email": email, "password": "longenough",
                                       "display_name": "N"})
    assert_error(r, 422, "validation_failed")
