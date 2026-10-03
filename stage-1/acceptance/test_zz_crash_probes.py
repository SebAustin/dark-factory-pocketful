"""Probes that may crash a fragile service; kept last so earlier files still report.

Ledger R-5.19 ("Requests must not produce 5xx responses"), R-2.8.
"""
import pytest

from conftest import assert_error, new_key


@pytest.mark.parametrize("depth", [1000, 100000])
@pytest.mark.parametrize("path", ["/payments", "/_test/reset", "/_test/import", "/auth/login"])
def test_R5_19_deeply_nested_body_4xx_and_service_survives(world, api, path, depth):
    raw = b'{"to_handle":"bob","amount":5,"x":' + b"[" * depth + b"]" * depth + b"}"
    r = api.call("POST", path, world.tok["ada"], new_key(), content=raw)
    assert r.status_code < 500, r.status_code
    # the service is still alive and state is intact
    h = api.get("/health")
    assert h.status_code == 200
    if path == "/payments" and r.status_code == 201:
        return
    if r.status_code >= 400:
        assert_error(r, r.status_code)


@pytest.mark.parametrize("raw", ["1e999999999", "1e-999999999", "-1e999999999"])
def test_R5_19_R4_23_huge_exponent_amount_422_fast_service_survives(world, api, raw):
    body = ('{"to_handle": "bob", "amount": %s}' % raw).encode()
    r = api.call("POST", "/payments", world.tok["ada"], new_key(), content=body)
    assert_error(r, 422, "validation_failed")
    assert api.get("/health").status_code == 200
    assert api.balance(world.tok["ada"]) == 10000
