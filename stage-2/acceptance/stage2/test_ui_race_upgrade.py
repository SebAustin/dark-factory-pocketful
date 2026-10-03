"""Screens: competing clients, uncertain outcomes, upgrade across export/import.

Ledger R2-RACE.1-8/10, R2-UPG.2/3/4/6.
"""
import pytest
from playwright.sync_api import expect

from s2lib import Api, STAGE1_URL, fixture, new_key, user
from uilib import Wire, fill_pay, goto, open_wallet, path_of, sign_in, text, tid


def test_R2_RACE_1_refresh_button_keeps_form(world, api, page):
    open_wallet(page, "ada@example.com")
    fill_pay(page, "bob", "12.34", "keep me")
    api.pay(world.tok["dee"], "ada", 500)            # another client changes state
    tid(page, "wallet-refresh").click()
    expect(tid(page, "wallet-balance")).to_have_text("105.00 EUR")
    assert tid(page, "pay-handle").input_value() == "bob"
    assert tid(page, "pay-amount").input_value() == "12.34"
    assert tid(page, "pay-note").input_value() == "keep me"


def test_R2_RACE_2_RACE_10_latest_refresh_wins_out_of_order(make_world, api, page):
    from s2lib import auth_rec
    w = make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 1000)])
    open_wallet(page, "ada@example.com")
    expect(tid(page, "wallet-available")).to_have_text("90.00 EUR")
    held = []
    mode = {"hold": True}

    def handler(route):
        if mode["hold"] and path_of(route.request.url) in ("/me", "/activity"):
            held.append((route, route.fetch()))   # stale snapshot taken now, released later
        else:
            route.continue_()

    page.route(lambda url: path_of(url) in ("/me", "/activity"), handler)
    tid(page, "wallet-refresh").click()             # refresh #1 (will be answered late)
    page.wait_for_timeout(600)
    assert held, "refresh did not read /me or /activity"
    api.pay(w.tok["dee"], "ada", 2000)              # state changes between the two refreshes
    api.capture(w.tok["bob"], "a_1", {"amount": 400, "final": False})
    mode["hold"] = False
    tid(page, "wallet-refresh").click()             # refresh #2 (answered first)
    expect(tid(page, "wallet-balance")).to_have_text("116.00 EUR")
    expect(tid(page, "wallet-available")).to_have_text("110.00 EUR")
    expect(tid(page, "wallet-held")).to_have_text("6.00 EUR")
    for route, resp in held:                        # now the delayed earlier read arrives
        route.fulfill(response=resp)
    page.wait_for_timeout(800)
    expect(tid(page, "wallet-balance")).to_have_text("116.00 EUR")
    expect(tid(page, "wallet-available")).to_have_text("110.00 EUR")
    expect(tid(page, "wallet-held")).to_have_text("6.00 EUR")


def test_R2_RACE_3_refused_payment_refreshes_and_keeps_inputs(world, api, page):
    open_wallet(page, "bob@example.com")
    expect(tid(page, "wallet-balance")).to_have_text("25.00 EUR")
    api.pay(world.tok["bob"], "ada", 2000)           # spent elsewhere after the page read it
    fill_pay(page, "cy", "10.00", "too late")
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-error")).to_be_visible()
    expect(tid(page, "wallet-balance")).to_have_text("5.00 EUR")
    expect(page.locator('[data-testid^="activity-item-"]')).to_have_count(1)
    assert tid(page, "pay-handle").input_value() == "cy"
    assert tid(page, "pay-amount").input_value() == "10.00"
    assert tid(page, "pay-note").input_value() == "too late"


def test_R2_RACE_4_cancelled_elsewhere_pay_shows_error_and_button_disappears(world, api, page):
    rid = api.request(world.tok["bob"], "ada", 100).json()["request_id"]
    sign_in(page, "ada@example.com")
    goto(page, "/requests")
    expect(tid(page, f"request-pay-{rid}")).to_be_visible()
    api.post(f"/requests/{rid}/cancel", world.tok["bob"])
    tid(page, f"request-pay-{rid}").click()
    expect(tid(page, "request-error")).to_be_visible()
    expect(tid(page, f"request-pay-{rid}")).to_have_count(0)
    expect(tid(page, f"request-item-{rid}")).to_have_attribute("data-status", "cancelled")
    assert world.me("ada")["total"] == 10000


def lose_first_payment(page, after_commit=True):
    state = {"n": 0}

    def handler(route):
        state["n"] += 1
        if state["n"] == 1:
            if after_commit:
                route.fetch()           # the server commits the payment ...
            route.abort("failed")       # ... and the browser never sees the answer
        else:
            route.continue_()

    page.route(lambda url: path_of(url) == "/payments", handler)
    return state


@pytest.mark.parametrize("after_commit", [True, False])
def test_R2_RACE_5_RACE_8_lost_response_shows_uncertain(world, page, after_commit):
    open_wallet(page, "ada@example.com")
    lose_first_payment(page, after_commit)
    fill_pay(page, "bob", "15.00", "lost")
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    assert text(page, "pay-uncertain") != ""
    expect(tid(page, "pay-error")).to_have_count(0)
    assert world.me("ada")["total"] == (8500 if after_commit else 10000)


@pytest.mark.parametrize("after_commit", [True, False])
def test_R2_RACE_6_RACE_7_retry_after_uncertain_same_key_same_body(world, page, after_commit):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    lose_first_payment(page, after_commit)
    fill_pay(page, "bob", "15.00", "lost")
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    tid(page, "pay-submit").click()                  # unchanged form: retry
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    expect(tid(page, "pay-error")).to_have_count(0)
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(page.locator('[data-testid^="activity-item-"]')).to_have_count(1)
    sent = wire.to("/payments")
    assert len(sent) == 2 and sent[0]["key"] == sent[1]["key"] and sent[0]["key"]
    assert sent[0]["body"] == sent[1]["body"]
    assert world.me("ada")["total"] == 8500 and world.me("bob")["total"] == 4000


# ---------------------------------------------------------------- upgrade

def test_R2_UPG_4_UPG_6_lost_payment_retry_after_import_recovers_original(world, api, page):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    lose_first_payment(page, after_commit=True)
    fill_pay(page, "bob", "15.00", "across the upgrade")
    tid(page, "pay-submit").click()
    expect(tid(page, "pay-uncertain")).to_be_visible()
    exported = api.export()                          # upgrade: export, replace, import
    api.reset(fixture())
    assert api.import_(exported).status_code == 204
    tid(page, "pay-submit").click()                  # no reload; same form, same key
    expect(tid(page, "pay-uncertain")).to_have_count(0)
    expect(tid(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(tid(page, "current-user")).to_be_visible()
    sent = wire.to("/payments")
    assert sent[0]["key"] == sent[-1]["key"] and sent[0]["body"] == sent[-1]["body"]
    assert world.me("ada")["total"] == 8500


@pytest.fixture
def s1():
    a = Api(STAGE1_URL)
    try:
        a.get("/health")
    except Exception as exc:
        pytest.fail(f"stage-1 service not reachable at {STAGE1_URL}: {exc}")
    yield a
    a.http.close()


def stage1_export(s1):
    s1.reset({"currency": "EUR", "minor_units": 2,
              "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500)],
              "payments": [], "requests": []})
    bob = s1.login("bob@example.com")
    rid = s1.request(bob, "ada", 1200).json()["request_id"]
    return s1.export(), rid


def test_R2_UPG_2_UPG_3_browser_stays_signed_in_and_pays_imported_request(api, s1, page):
    api.reset(fixture(users=[user("u_ada", "ada", 10000), user("u_bob", "bob", 2500)],
                      settlement_operator_ids=[]))
    open_wallet(page, "ada@example.com")             # signed in before the upgrade
    fill_pay(page, "bob", "1.00", "kept")
    exported, rid = stage1_export(s1)
    assert api.import_(exported).status_code == 204
    page.locator('a[href="/requests"]:visible').first.click()  # no reload: in-app navigation
    expect(tid(page, "current-user")).to_be_visible()
    expect(tid(page, f"request-pay-{rid}")).to_be_visible()
    tid(page, f"request-pay-{rid}").click()
    expect(tid(page, f"request-item-{rid}")).to_have_attribute("data-status", "paid")
    page.locator('a[href="/"]:visible').first.click()
    expect(tid(page, "wallet-balance")).to_have_text("88.00 EUR")
