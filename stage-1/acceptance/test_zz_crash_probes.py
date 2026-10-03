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


def test_R3_10_R5_19_huge_exponent_in_unknown_field_ignored(world, api):
    # unknown fields are ignored, never an error: the payment itself is valid
    body = b'{"to_handle": "bob", "amount": 5, "extra": 1e999999999}'
    r = api.call("POST", "/payments", world.tok["ada"], new_key(), content=body)
    assert r.status_code == 201, r.text
    assert api.get("/health").status_code == 200


def test_R10_8_R5_19_import_huge_exponent_422_fast(world, api):
    raw = b'{"track":"pocketful","format_version":1,"state":{"seq":1e999999999}}'
    r = api.call("POST", "/_test/import", content=raw, timeout=10.0)
    assert_error(r, 422, "validation_failed")
    assert api.get("/health").status_code == 200
    assert api.balance(world.tok["ada"]) == 10000


@pytest.mark.parametrize("field", ["note"])
def test_R8_13_R5_19_lone_surrogate_note_rejected_feed_survives(world, api, field):
    # "\ud800" is not a Unicode scalar value; it cannot round-trip "byte for byte"
    raw = ('{"to_handle":"cy","amount":5,"%s":"\\ud800"}' % field).encode()
    r = api.call("POST", "/payments", world.tok["dee"], new_key(), content=raw)
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})
    assert api.balance(world.tok["dee"]) == 5000
    for tok in world.tok.values():
        assert api.get("/activity", tok).status_code == 200


def test_R5_19_lone_surrogate_display_name_rejected(world, api):
    raw = b'{"email":"sur@example.org","password":"longenough","display_name":"\\udc00"}'
    r = api.call("POST", "/auth/signup", content=raw)
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})
    assert api.get("/me", world.tok["ada"]).status_code == 200


def test_R5_19_lone_surrogate_request_and_split_note_rejected(world, api):
    raw = b'{"payer_handle":"ada","amount":5,"note":"\\ud800"}'
    r = api.call("POST", "/requests", world.tok["bob"], new_key(), content=raw)
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})
    raw = b'{"amount":5,"participant_handles":["bob","ada"],"note":"\\ud800"}'
    r = api.call("POST", "/splits", world.tok["bob"], new_key(), content=raw)
    assert_error(r, {400, 422}, {"malformed_request", "validation_failed"})
    for tok in world.tok.values():
        assert api.get("/requests", tok).status_code == 200
