"""Screens: activity feed, requests, split, refresh after actions.

Ledger R2-FEED, R2-REQ, R2-SPL, R2-SYNC, R2-VIS.11.
"""
import time

from playwright.sync_api import expect

from s2lib import fixture, fmt, new_key
from uilib import T, Wire, goto, open_wallet, sign_in, text, tid


def items(page, prefix):
    return page.locator(f'[data-testid^="{prefix}"]').evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")


# ---------------------------------------------------------------- feed

def test_R2_FEED_1_activity_newest_first_dom_order(world, api, page):
    ids = []
    for i in range(3):
        ids.append(api.pay(world.tok["ada"], "bob", 100 + i).json()["payment_id"])
        if i < 2:
            time.sleep(1.1)
    open_wallet(page, "cy@example.com")
    expect(tid(page, "activity-list")).to_be_visible()
    got = tid(page, "activity-list").locator('[data-testid^="activity-item-"]').evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert got == [f"activity-item-{p}" for p in reversed(ids)]


def test_R2_FEED_2_FEED_8_activity_items_match_api_feed(make_world, api, page):
    w = make_world(payments=[{"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
                              "amount": 5, "note": "", "visibility": "private"}])
    pub = api.pay(w.tok["dee"], "bob", 7).json()["payment_id"]
    priv = api.pay(w.tok["ada"], "dee", 9, visibility="private").json()["payment_id"]
    open_wallet(page, "bob@example.com")
    expect(tid(page, f"activity-item-{pub}")).to_be_visible()
    shown = set(items(page, "activity-item-"))
    assert shown == {"activity-item-p_seed", f"activity-item-{pub}"}
    assert priv not in "".join(shown)
    expect(tid(page, "activity-item-p_seed")).to_have_attribute("data-visibility", "private")
    expect(tid(page, f"activity-item-{pub}")).to_have_attribute("data-visibility", "public")


def test_R2_FEED_3_FEED_4_FEED_5_activity_item_fields(world, api, page):
    note = '  <b>bold</b> & "q" 🍕  '
    p1 = api.pay(world.tok["ada"], "bob", 1550, note=note).json()["payment_id"]
    p2 = api.pay(world.tok["ada"], "bob", 1).json()["payment_id"]
    open_wallet(page, "ada@example.com")
    parties = text(page, f"activity-parties-{p1}")
    assert "ada" in parties and "bob" in parties
    expect(tid(page, f"activity-amount-{p1}")).to_have_text("15.50 EUR")
    assert tid(page, f"activity-note-{p1}").text_content() == note
    assert page.locator(f'{T("activity-note-" + p1)} b').count() == 0  # text, not markup
    expect(tid(page, f"activity-note-{p2}")).to_have_count(1)
    assert tid(page, f"activity-note-{p2}").text_content() == ""


def test_R2_FEED_6_REQ_7_AUI_16_VIS_11_empty_states(world, page):
    open_wallet(page, "cy@example.com")
    expect(tid(page, "empty-activity")).to_be_visible()
    expect(tid(page, "activity-list")).to_have_count(0)
    goto(page, "/requests")
    expect(tid(page, "empty-requests")).to_be_visible()
    goto(page, "/authorizations")
    expect(tid(page, "empty-authorizations")).to_be_visible()


# ---------------------------------------------------------------- requests

def mkreq(api, w, requester, payer, amount):
    return api.request(w.tok[requester], payer, amount).json()["request_id"]


def test_R2_REQ_1_REQ_2_REQ_3_lists_and_statuses(world, api, page):
    t = world.tok
    inc = mkreq(api, world, "bob", "ada", 1200)
    out = mkreq(api, world, "ada", "dee", 300)
    paid = mkreq(api, world, "bob", "ada", 100)
    api.post(f"/requests/{paid}/pay", t["ada"], new_key(), {})
    dec = mkreq(api, world, "bob", "ada", 100)
    api.post(f"/requests/{dec}/decline", t["ada"])
    can = mkreq(api, world, "ada", "bob", 100)
    api.post(f"/requests/{can}/cancel", t["ada"])
    sign_in(page, "ada@example.com")
    goto(page, "/requests")
    expect(tid(page, f"request-item-{inc}")).to_be_visible()
    assert tid(page, "incoming-list").locator(T(f"request-item-{inc}")).count() == 1
    assert tid(page, "outgoing-list").locator(T(f"request-item-{out}")).count() == 1
    for rid, st in ((inc, "pending"), (out, "pending"), (paid, "paid"), (dec, "declined"),
                    (can, "cancelled")):
        expect(tid(page, f"request-item-{rid}")).to_have_attribute("data-status", st)
    expect(tid(page, f"request-amount-{inc}")).to_have_text("12.00 EUR")
    expect(tid(page, f"request-amount-{out}")).to_have_text("3.00 EUR")


def test_R2_REQ_4_REQ_5_action_buttons_only_where_allowed(world, api, page):
    t = world.tok
    inc = mkreq(api, world, "bob", "ada", 100)
    out = mkreq(api, world, "ada", "dee", 100)
    paid = mkreq(api, world, "bob", "ada", 100)
    api.post(f"/requests/{paid}/pay", t["ada"], new_key(), {})
    sign_in(page, "ada@example.com")
    goto(page, "/requests")
    expect(tid(page, f"request-item-{inc}")).to_be_visible()
    for name, present in ((f"request-pay-{inc}", 1), (f"request-decline-{inc}", 1),
                          (f"request-cancel-{inc}", 0), (f"request-cancel-{out}", 1),
                          (f"request-pay-{out}", 0), (f"request-decline-{out}", 0),
                          (f"request-pay-{paid}", 0), (f"request-decline-{paid}", 0)):
        expect(tid(page, name)).to_have_count(present)


def test_R2_REQ_8_SYNC_1_pay_decline_cancel_buttons(world, api, page):
    t = world.tok
    a = mkreq(api, world, "bob", "ada", 1200)
    b = mkreq(api, world, "bob", "ada", 100)
    c = mkreq(api, world, "ada", "dee", 100)
    sign_in(page, "ada@example.com")
    goto(page, "/requests")
    tid(page, f"request-pay-{a}").click()
    expect(tid(page, f"request-item-{a}")).to_have_attribute("data-status", "paid")
    expect(tid(page, f"request-pay-{a}")).to_have_count(0)
    tid(page, f"request-decline-{b}").click()
    expect(tid(page, f"request-item-{b}")).to_have_attribute("data-status", "declined")
    tid(page, f"request-cancel-{c}").click()
    expect(tid(page, f"request-item-{c}")).to_have_attribute("data-status", "cancelled")
    assert world.me("ada")["total"] == 8800 and world.me("bob")["total"] == 3700


def test_R2_REQ_6_pay_short_shows_request_error(world, api, page):
    rid = mkreq(api, world, "ada", "cy", 500)
    sign_in(page, "cy@example.com")
    goto(page, "/requests")
    tid(page, f"request-pay-{rid}").click()
    expect(tid(page, "request-error")).to_be_visible()
    expect(tid(page, f"request-item-{rid}")).to_have_attribute("data-status", "pending")


# ---------------------------------------------------------------- split

def fill_split(page, amount, handles, note=""):
    tid(page, "split-amount").fill(amount)
    tid(page, "split-handles").fill(handles)
    tid(page, "split-note").fill(note)


def test_R2_SPL_3_SPL_4_preview_before_any_post_matches_s9(world, page):
    wire = Wire(page)
    sign_in(page, "ada@example.com")
    goto(page, "/split")
    for amount, handles, expected in (("10.00", "ada, bob,cy", ["3.34", "3.33", "3.33"]),
                                      ("0.01", "ada,bob,cy", ["0.01", "0.00", "0.00"]),
                                      ("0.10", "bob,cy,dee", ["0.04", "0.03", "0.03"]),
                                      ("9.99", "ada,bob,cy", ["3.33", "3.33", "3.33"]),
                                      ("0.05", "ada,bob,cy,dee,op", ["0.01"] * 5)):
        fill_split(page, amount, handles)
        names = [h.strip() for h in handles.split(",")]
        expect(tid(page, "split-preview")).to_be_visible()
        for h, e in zip(names, expected):
            expect(tid(page, "split-preview").locator(T(f"split-share-{h}"))).to_have_text(
                e + " EUR")
    assert wire.to("/splits") == []


def test_R2_SPL_6_SPL_1_SPL_2_preview_equals_server_shares_in_order(world, api, page):
    wire = Wire(page)
    sign_in(page, "ada@example.com")
    goto(page, "/split")
    fill_split(page, "0.10", "dee, cy , bob", "pizza")
    expect(tid(page, "split-share-dee")).to_have_text("0.04 EUR")
    preview = {h: text(page, f"split-share-{h}") for h in ("dee", "cy", "bob")}
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_have_count(0)
    page.wait_for_timeout(800)
    sent = wire.to("/splits")
    assert len(sent) == 1
    assert sent[0]["body"]["participant_handles"] == ["dee", "cy", "bob"]
    assert sent[0]["body"]["amount"] == 10
    reqs = api.get("/requests", world.tok["ada"]).json()["requests"]
    server = {q["payer_handle"]: fmt(q["amount"], 2, "EUR") for q in reqs}
    assert server == preview


def test_R2_SPL_5_split_error_unknown_or_duplicate(world, page):
    sign_in(page, "ada@example.com")
    goto(page, "/split")
    fill_split(page, "3.00", "bob, nobody")
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_be_visible()
    fill_split(page, "3.00", "bob, bob")
    tid(page, "split-submit").click()
    expect(tid(page, "split-error")).to_be_visible()


# ---------------------------------------------------------------- refresh after actions

def test_R2_SYNC_2_refresh_waits_for_write(world, page):
    open_wallet(page, "ada@example.com")
    order = []
    page.on("request", lambda r: order.append(("req", r.method, r.url.split("?")[0])))
    page.on("response", lambda r: order.append(("resp", r.request.method,
                                                 r.url.split("?")[0])))

    def slow(route):
        page.wait_for_timeout(1500)
        route.continue_()

    page.route("**/payments", slow)
    tid(page, "pay-handle").fill("bob")
    tid(page, "pay-amount").fill("1")
    tid(page, "pay-submit").click()
    expect(tid(page, "wallet-balance")).to_have_text("99.00 EUR")
    post_done = next(i for i, e in enumerate(order)
                     if e[0] == "resp" and e[1] == "POST" and e[2].endswith("/payments"))
    me_reads = [i for i, e in enumerate(order)
                if e[0] == "req" and e[1] == "GET" and e[2].endswith("/me")]
    assert me_reads and all(i > post_done for i in me_reads), order
