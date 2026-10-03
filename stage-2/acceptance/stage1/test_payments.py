"""§8 POST /payments and §5 field rules. Ledger R-1.9/1.10, R-4.2-4.4, R-4.11, R-5.x, R-8.2-8.13."""
import pytest

from conftest import PAYMENT_KEYS, RFC3339, assert_error, new_key


def test_R8_5_R1_1_send_by_handle_201(world, api):
    r = api.pay(world.tok["ada"], "bob", 1500, note="dinner", visibility="public")
    assert r.status_code == 201
    p = r.json()
    assert set(p) == PAYMENT_KEYS, set(p) ^ PAYMENT_KEYS
    assert p["from_user_id"] == "u_ada" and p["from_handle"] == "ada"
    assert p["to_user_id"] == "u_bob" and p["to_handle"] == "bob"
    assert p["amount"] == 1500 and p["currency"] == "EUR"
    assert p["note"] == "dinner" and p["visibility"] == "public"
    assert p["request_id"] is None
    assert p["settlement_id"] is None
    assert RFC3339.match(p["created_at"])


def test_R4_11_balances_move_immediately(world, api):
    api.pay(world.tok["ada"], "bob", 1500)
    assert api.balance(world.tok["ada"]) == 8500
    assert api.balance(world.tok["bob"]) == 4000


def test_R1_9_R4_2_amount_returned_as_json_integer(world, api):
    r = api.pay(world.tok["ada"], "bob", 7)
    assert '"amount":7' in r.text.replace(" ", "")
    assert type(r.json()["amount"]) is int


@pytest.mark.parametrize("raw", ["1000.0", "1e3", "1E3", "1000.000", "10e2"])
def test_R4_3_amount_float_forms_accepted(world, api, raw):
    body = '{"to_handle": "bob", "amount": %s}' % raw
    r = api.call("POST", "/payments", world.tok["ada"], new_key(), content=body.encode())
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == 1000
    assert type(r.json()["amount"]) is int
    assert api.balance(world.tok["ada"]) == 9000


@pytest.mark.parametrize("amount", [True, False, "1000", "1e3", None, [1000], {"v": 1}])
def test_R4_4_R5_11_amount_bool_string_null_422(world, api, amount):
    assert_error(api.pay(world.tok["ada"], "bob", amount), 422, "validation_failed")
    assert api.balance(world.tok["ada"]) == 10000


@pytest.mark.parametrize("raw,ok", [
    ("0", False), ("-1", False), ("1", True), ("1000000000", True), ("1000000001", False),
    ("10.5", False), ("1000.0000001", False), ("-0", False), ("1e9", True), ("1e400", False),
    ("1" + "0" * 5000, False), ("0.5e1", True),
])
def test_R8_7_R4_23_amount_bounds(make_world, api, raw, ok):
    from conftest import user
    w = make_world(users=[user("u_ada", "ada", 2_000_000_000), user("u_bob", "bob", 0)])
    body = '{"to_handle": "bob", "amount": %s}' % raw
    r = api.call("POST", "/payments", w.tok["ada"], new_key(), content=body.encode())
    if ok:
        assert r.status_code == 201, r.text
    else:
        assert_error(r, 422, "validation_failed")
        assert api.balance(w.tok["ada"]) == 2_000_000_000


def test_R5_9_missing_required_fields_422(world, api):
    t = world.tok["ada"]
    assert_error(api.post("/payments", t, new_key(), {"amount": 5}), 422, "validation_failed")
    assert_error(api.post("/payments", t, new_key(), {"to_handle": "bob"}), 422,
                 "validation_failed")


def test_R5_13_wrong_type_handle_400(world, api):
    r = api.post("/payments", world.tok["ada"], new_key(), {"to_handle": 5, "amount": 5})
    assert_error(r, 400, "malformed_request")
    r = api.post("/payments", world.tok["ada"], new_key(), {"to_handle": ["bob"], "amount": 5})
    assert_error(r, 400, "malformed_request")


def test_R8_8_self_payment_422(world, api):
    assert_error(api.pay(world.tok["ada"], "ada", 5), 422, "self_payment")
    assert api.balance(world.tok["ada"]) == 10000


def test_R8_9_R5_10_note_length(world, api):
    assert api.pay(world.tok["ada"], "bob", 1, note="n" * 200).status_code == 201
    assert_error(api.pay(world.tok["ada"], "bob", 1, note="n" * 201), 422, "validation_failed")


@pytest.mark.parametrize("note", [None, 5, [], {}, True])
def test_R5_11_note_non_string_422(world, api, note):
    assert_error(api.pay(world.tok["ada"], "bob", 1, note=note), 422, "validation_failed")


@pytest.mark.parametrize("vis", [None, "PUBLIC", "friends", "", 1, True, ["public"]])
def test_R8_10_R5_11_visibility_invalid_422(world, api, vis):
    assert_error(api.pay(world.tok["ada"], "bob", 1, visibility=vis), 422, "validation_failed")


def test_R8_4_R5_12_defaults_note_empty_visibility_public(world, api):
    p = api.pay(world.tok["ada"], "bob", 1).json()
    assert p["note"] == "" and p["visibility"] == "public"


def test_R8_11_R1_10_unknown_handle_404_no_movement(world, api):
    assert_error(api.pay(world.tok["ada"], "nobody", 5), 404, "not_found")
    assert api.balance(world.tok["ada"]) == 10000


def test_R5_10_invalid_handle_format(world, api):
    for h in ("BOB", "", "b" * 21, "bo b"):
        assert_error(api.pay(world.tok["ada"], h, 5), {404, 422}, {"not_found",
                                                                    "validation_failed"})


def test_R8_6_insufficient_409_no_change(world, api):
    assert_error(api.pay(world.tok["bob"], "ada", 2501), 409, "insufficient_funds")
    assert api.balance(world.tok["bob"]) == 2500
    assert api.balance(world.tok["ada"]) == 10000


def test_R8_6_exact_balance_ok_to_zero(world, api):
    assert api.pay(world.tok["bob"], "ada", 2500).status_code == 201
    assert api.balance(world.tok["bob"]) == 0
    assert_error(api.pay(world.tok["bob"], "ada", 1), 409, "insufficient_funds")


def test_R8_12_failed_payment_leaves_no_trace(world, api):
    t = world.tok["bob"]
    before_b = world.balances()
    feeds = {h: api.feed(tok)["payments"] for h, tok in world.tok.items()}
    api.pay(t, "ada", 999999)                  # insufficient
    api.pay(t, "nobody", 5)                    # unknown
    api.pay(t, "bob", 5)                       # self
    api.pay(t, "ada", 0)                       # invalid amount
    api.pay(t, "ada", 5, note="x" * 201)       # note too long
    assert world.balances() == before_b
    assert {h: api.feed(tok)["payments"] for h, tok in world.tok.items()} == feeds


def test_R8_13_note_verbatim_roundtrip(world, api):
    note = "  <b>&amp;</b> \"q\" \\n \n\t \U0001F355\U0001F469‍\U0001F469‍\U0001F467" \
           " é vs é  "
    r = api.pay(world.tok["ada"], "bob", 1, note=note, visibility="private")
    assert r.status_code == 201
    assert r.json()["note"] == note
    for h in ("ada", "bob"):
        notes = [p["note"] for p in api.feed(world.tok[h])["payments"]]
        assert notes == [note]
    q = api.request(world.tok["ada"], "bob", 1, note=note)
    assert q.json()["note"] == note
    assert api.requests_list(world.tok["bob"])["requests"][0]["note"] == note


def test_R3_10_unknown_fields_ignored_cannot_spoof_sender(world, api):
    r = api.post("/payments", world.tok["ada"], new_key(), {
        "to_handle": "bob", "amount": 100, "from_handle": "dee", "from_user_id": "u_dee",
        "currency": "USD", "payment_id": "p_mine", "created_at": "2000-01-01T00:00:00Z",
        "extra": {"nested": [1, 2]},
    })
    assert r.status_code == 201
    p = r.json()
    assert p["from_user_id"] == "u_ada" and p["currency"] == "EUR"
    assert api.balance(world.tok["ada"]) == 9900
    assert api.balance(world.tok["dee"]) == 5000
