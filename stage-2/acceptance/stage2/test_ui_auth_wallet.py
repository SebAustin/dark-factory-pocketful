"""Screens: signup/login, wallet numbers, pay and request forms, amount input and formatting.

Ledger R2-SIGN, R2-PAY, R2-AMT, R2-AUI.2-4/17, R2-SCR.2/3.
"""
import re

import pytest
from playwright.sync_api import expect

from s2lib import auth_rec, fixture, fmt, user
from uilib import T, Wire, fill_pay, goto, open_wallet, sign_in, text, tid

ROUTES = ["/", "/requests", "/split", "/authorizations"]


# ---------------------------------------------------------------- signup / login

def test_R2_SIGN_1_SIGN_5_signup_flow_signs_in(world, page):
    goto(page, "/signup")
    expect(tid(page, "auth-error")).to_have_count(0)
    tid(page, "signup-email").fill("Nina.K@example.org")
    tid(page, "signup-password").fill("longenough")
    tid(page, "signup-display-name").fill("Nina K")
    tid(page, "signup-submit").click()
    expect(tid(page, "current-user")).to_contain_text("Nina K")
    expect(tid(page, "current-handle")).to_have_text("nina_k")


def test_R2_SIGN_2_login_flow_signs_in(world, page):
    sign_in(page, "bob@example.com")
    expect(tid(page, "current-user")).to_contain_text("Bob")


def test_R2_SIGN_3_auth_error_only_on_error(world, page):
    goto(page, "/login")
    expect(tid(page, "auth-error")).to_have_count(0)
    tid(page, "login-email").fill("ada@example.com")
    tid(page, "login-password").fill("wrong horse")
    tid(page, "login-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()
    tid(page, "login-password").fill("correct horse")
    tid(page, "login-submit").click()
    expect(tid(page, "current-user")).to_be_visible()
    expect(tid(page, "auth-error")).to_have_count(0)
    # signup refusals: email taken, short password
    page.context.clear_cookies()
    page.evaluate("() => localStorage.clear()")
    goto(page, "/signup")
    tid(page, "signup-email").fill("ada@example.com")
    tid(page, "signup-password").fill("longenough")
    tid(page, "signup-display-name").fill("Ada 2")
    tid(page, "signup-submit").click()
    expect(tid(page, "auth-error")).to_be_visible()


def test_R2_SIGN_4_SIGN_5_current_user_and_handle_on_every_route(world, page):
    sign_in(page, "dee@example.com")
    for route in ROUTES:
        goto(page, route)
        expect(tid(page, "current-user")).to_contain_text("Dee")
        expect(tid(page, "current-handle")).to_have_text("dee")


def test_R2_SIGN_6_logout_signs_out(world, page):
    sign_in(page, "ada@example.com")
    tid(page, "logout-button").click()
    expect(tid(page, "current-user")).to_have_count(0)
    goto(page, "/")
    expect(tid(page, "current-user")).to_have_count(0)
    expect(tid(page, "login-email")).to_be_visible()


def test_R2_SCR_3_navigation_reaches_every_screen(world, page):
    sign_in(page, "ada@example.com")
    goto(page, "/")
    for target in ("/requests", "/split", "/authorizations", "/"):
        page.locator(f'a[href="{target}"]:visible').first.click()
        expect(page).to_have_url(re.compile(re.escape(target) + "$"))


# ---------------------------------------------------------------- wallet numbers

def test_R2_PAY_1_AUI_2_wallet_balance_text_and_data_amount(world, page):
    open_wallet(page, "ada@example.com")
    expect(tid(page, "wallet-balance")).to_have_text("100.00 EUR")
    expect(tid(page, "wallet-balance")).to_have_attribute("data-amount", "10000")
    expect(tid(page, "wallet-available")).to_have_text("100.00 EUR")
    expect(tid(page, "wallet-available")).to_have_attribute("data-amount", "10000")


def test_R2_AUI_4_AUI_17_seeded_hold_shown_right_after_reset(make_world, page):
    make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 2000)])
    open_wallet(page, "ada@example.com")
    expect(tid(page, "wallet-available")).to_have_text("80.00 EUR")
    expect(tid(page, "wallet-available")).to_have_attribute("data-amount", "8000")
    expect(tid(page, "wallet-balance")).to_have_text("100.00 EUR")
    expect(tid(page, "wallet-held")).to_have_text("20.00 EUR")
    expect(tid(page, "wallet-held")).to_have_attribute("data-amount", "2000")


def test_R2_AUI_4_wallet_held_absent_when_zero(world, page):
    open_wallet(page, "bob@example.com")
    expect(tid(page, "wallet-held")).to_have_count(0)


# ---------------------------------------------------------------- pay / request forms

def test_R2_PAY_2_PAY_6_pay_flow_moves_money_and_keeps_values(world, api, page):
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", "15.00", "dinner 🍝")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    assert world.me("bob")["total"] == 4000
    assert tid(page, "pay-handle").input_value() == "bob"
    assert tid(page, "pay-amount").input_value() == "15.00"
    assert tid(page, "pay-note").input_value() == "dinner 🍝"
    expect(tid(page, "pay-error")).to_have_count(0)


def test_R2_PAY_3_pay_visibility_options_and_private(world, api, page):
    open_wallet(page, "ada@example.com")
    values = tid(page, "pay-visibility").locator("option").evaluate_all(
        "els => els.map(e => e.value)")
    assert sorted(values) == ["private", "public"]
    fill_pay(page, "bob", "1", visibility="private")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("99.00 EUR")
    assert api.feed(world.tok["ada"])["payments"][0]["visibility"] == "private"
    assert api.feed(world.tok["cy"])["payments"] == []


@pytest.mark.parametrize("handle,amount", [("bob", "100.01"), ("nobody", "1"), ("ada", "1")])
def test_R2_PAY_4_pay_error_insufficient_unknown_self(world, page, handle, amount):
    open_wallet(page, "ada@example.com")
    fill_pay(page, handle, amount)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    expect(tid(page, "wallet-balance")).to_have_text("100.00 EUR")


def test_R2_PAY_5_request_form_creates_request_and_errors(world, api, page):
    open_wallet(page, "bob@example.com")
    tid(page, "request-handle").fill("ada")
    tid(page, "request-amount").fill("12.00")
    tid(page, "request-note").fill("taxi")
    tid(page, "request-submit").click()
    expect(tid(page, "request-error")).to_have_count(0)
    page.wait_for_function("() => true")
    reqs = api.get("/requests", world.tok["ada"]).json()["requests"]
    assert [(q["amount"], q["note"], q["status"]) for q in reqs] == [(1200, "taxi", "pending")]
    tid(page, "request-handle").fill("bob")
    tid(page, "request-submit").click()
    expect(tid(page, "request-error")).to_be_visible()


def test_R2_PAY_7_resubmit_unchanged_is_not_a_new_payment(world, page):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", "15.00", "once")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    tid(page, "pay-submit").click()
    page.wait_for_timeout(1200)
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(tid(page, "pay-error")).to_have_count(0)
    expect(page.locator('[data-testid^="activity-item-"]')).to_have_count(1)
    keys = {w["key"] for w in wire.to("/payments")}
    assert len(keys) == 1, wire.writes  # any resend is a replay with the same key
    assert world.me("ada")["total"] == 8500


def test_R2_PAY_8_changed_field_new_payment(world, page):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", "15.00")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    tid(page, "pay-amount").fill("5.00")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("80.00 EUR")
    keys = [w["key"] for w in wire.to("/payments")]
    assert len(set(keys)) == 2
    expect(page.locator('[data-testid^="activity-item-"]')).to_have_count(2)


# ---------------------------------------------------------------- amounts

@pytest.mark.parametrize("typed,minor", [("15.00", 1500), ("15", 1500), ("15.5", 1550),
                                         ("0.01", 1), (" 2.50 ", 250)])
def test_R2_AMT_1_AMT_6_decimal_inputs_submit_minor_units(world, page, typed, minor):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", typed)
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text(fmt(10000 - minor, 2, "EUR"))
    assert wire.to("/payments")[0]["body"]["amount"] == minor


@pytest.mark.parametrize("typed", ["15.005", "abc", "1e3", "15,00", "", "-5", "1.2.3"])
def test_R2_AMT_7_bad_amount_shows_error_no_request(world, page, typed):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", typed)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    page.wait_for_timeout(500)
    assert wire.to("/payments") == []
    assert world.me("ada")["total"] == 10000


@pytest.mark.parametrize("cur,mu,bal,shown,bad,good,minor", [
    ("JPY", 0, 120000, "120000 JPY", "15.0", "1500", 1500),
    ("BHD", 3, 12345, "12.345 BHD", "1.0005", "1.5", 1500),
    ("EUR", 2, 123456789, "1234567.89 EUR", "0.001", "0.05", 5),
])
def test_R2_AMT_2_AMT_3_AMT_4_AMT_7_formatted_amount_per_minor_units(make_world, page, cur, mu,
                                                                     bal, shown, bad, good,
                                                                     minor):
    make_world(fixture(currency=cur, minor_units=mu,
                       users=[user("u_ada", "ada", bal), user("u_bob", "bob", 0)],
                       settlement_operator_ids=[]))
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    expect(tid(page, "wallet-balance")).to_have_text(shown)
    expect(tid(page, "wallet-available")).to_have_text(shown)
    fill_pay(page, "bob", bad)
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    assert wire.to("/payments") == []
    fill_pay(page, "bob", good)
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text(fmt(bal - minor, mu, cur))
    assert wire.to("/payments")[-1]["body"]["amount"] == minor
    item = page.locator('[data-testid^="activity-amount-"]').first
    expect(item).to_have_text(fmt(minor, mu, cur))


def test_R2_AMT_8_same_rule_on_request_split_authorize_forms(world, page):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    tid(page, "request-handle").fill("bob")
    tid(page, "request-amount").fill("1.005")
    tid(page, "request-submit").click()
    expect(tid(page, "request-error")).to_be_visible()
    tid(page, "authorize-handle").fill("bob")
    tid(page, "authorize-amount").fill("abc")
    tid(page, "authorize-submit").click()
    expect(tid(page, "authorize-error")).to_be_visible()
    goto(page, "/split")
    tid(page, "split-amount").fill("10.001")
    tid(page, "split-handles").fill("ada, bob")
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_be_visible()
    page.wait_for_timeout(400)
    assert wire.writes == []


@pytest.mark.parametrize("form,fields,path", [
    ("request", {"request-handle": "ada", "request-amount": "12.00"}, "/requests"),
    ("pay", {"pay-handle": "ada", "pay-amount": "1.00"}, "/payments"),
])
def test_R2_PAY_8_edit_during_inflight_then_submit_sends_new_request(world, page, form, fields,
                                                                     path):
    """A field changed while the previous submission is in flight makes the next click a new
    request (R2-PAY.8); the click must not be lost."""
    wire = Wire(page)
    open_wallet(page, "bob@example.com")
    for k, v in fields.items():
        tid(page, k).fill(v)
    held = []
    page.route(lambda url: url.endswith(path), lambda route: held.append(route))
    tid(page, f"{form}-submit").click()
    page.wait_for_timeout(300)
    assert len(held) == 1
    tid(page, f"{form}-handle").fill("dee")          # edited while the first is in flight
    page.unroute(lambda url: url.endswith(path))
    held[0].continue_()
    page.wait_for_timeout(1200)                      # first submission done and refreshed
    tid(page, f"{form}-submit").click()
    page.wait_for_timeout(1500)
    handles = [w["body"].get("payer_handle") or w["body"].get("to_handle")
               for w in wire.to(path)]
    assert handles == ["ada", "dee"], handles
