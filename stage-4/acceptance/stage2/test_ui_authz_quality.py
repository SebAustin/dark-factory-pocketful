"""Screens: authorizations UI and product quality (viewport, labels, focus, contrast, assets).

Ledger R2-AUI, R2-VIS.2/3/5/7-12, R2-SCR.2/8.
"""
import time
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from s2lib import TARGET_URL, auth_rec, fixture, iso, now_utc, user
from uilib import Wire, goto, open_wallet, sign_in, text, tid

ROUTES = ["/", "/requests", "/split", "/authorizations"]


def authz_page(page, email):
    sign_in(page, email)
    goto(page, "/authorizations")


# ---------------------------------------------------------------- authorizations UI

def test_R2_AUI_5_authorize_form_creates_hold(world, page):
    wire = Wire(page)
    open_wallet(page, "ada@example.com")
    tid(page, "authorize-handle").fill("bob")
    tid(page, "authorize-amount").fill("20.00")
    tid(page, "authorize-note").fill("deposit")
    tid(page, "authorize-visibility").select_option("private")
    tid(page, "authorize-submit").click()
    expect(tid(page, "wallet-available")).to_have_text("80.00 EUR")
    expect(tid(page, "wallet-held")).to_have_text("20.00 EUR")
    expect(tid(page, "wallet-balance")).to_have_text("100.00 EUR")
    sent = wire.to("/authorizations")
    assert sent[0]["body"]["amount"] == 2000 and sent[0]["key"]


def test_R2_AUI_6_authorize_error_insufficient_available(make_world, page):
    make_world(authorizations=[auth_rec("a_1", "u_bob", "u_ada", 2000)])
    open_wallet(page, "bob@example.com")
    tid(page, "authorize-handle").fill("ada")
    tid(page, "authorize-amount").fill("5.01")
    tid(page, "authorize-submit").click()
    expect(tid(page, "authorize-error")).to_be_visible()


def test_R2_AUI_7_authorization_list_newest_first(world, api, page):
    ids = []
    for i in range(3):
        ids.append(api.authorize(world.tok["ada"], "bob", 10 + i).json()["authorization_id"])
        if i < 2:
            time.sleep(1.1)
    authz_page(page, "ada@example.com")
    expect(tid(page, "authorization-list")).to_be_visible()
    got = tid(page, "authorization-list").locator('[data-testid^="authorization-item-"]'
                                                   ).evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert got == [f"authorization-item-{a}" for a in reversed(ids)]


def test_R2_AUI_8_AUI_9_AUI_10_AUI_11_items_status_and_fields(make_world, api, page):
    past = iso(now_utc() - timedelta(hours=2))
    w = make_world(authorizations=[auth_rec("a_exp", "u_ada", "u_bob", 300, status="open",
                                            expires_at=past)])
    o = api.authorize(w.tok["ada"], "bob", 2000).json()
    c = api.authorize(w.tok["ada"], "bob", 1000).json()
    api.capture(w.tok["bob"], c["authorization_id"], {"amount": 400})
    p = api.authorize(w.tok["ada"], "bob", 1000).json()
    api.capture(w.tok["bob"], p["authorization_id"], {"amount": 250, "final": False})
    v = api.authorize(w.tok["ada"], "bob", 500).json()
    api.void(w.tok["ada"], v["authorization_id"])
    authz_page(page, "ada@example.com")
    for aid, st in ((o["authorization_id"], "open"), (c["authorization_id"], "captured"),
                    (p["authorization_id"], "open"), (v["authorization_id"], "voided"),
                    ("a_exp", "expired")):
        expect(tid(page, f"authorization-item-{aid}")).to_have_attribute("data-status", st)
    expect(tid(page, f"authorization-amount-{o['authorization_id']}")).to_have_text("20.00 EUR")
    expect(tid(page, f"authorization-captured-{c['authorization_id']}")).to_have_text(
        "4.00 EUR")
    for aid in (o["authorization_id"], p["authorization_id"], v["authorization_id"], "a_exp"):
        expect(tid(page, f"authorization-captured-{aid}")).to_have_count(0)
    expect(tid(page, f"authorization-expires-{o['authorization_id']}")).to_have_text(
        o["expires_at"])


def test_R2_AUI_12_AUI_13_AUI_14_controls_by_direction_and_status(world, api, page):
    out = api.authorize(world.tok["ada"], "bob", 2000).json()["authorization_id"]
    inc = api.authorize(world.tok["dee"], "ada", 1550).json()["authorization_id"]
    closed = api.authorize(world.tok["dee"], "ada", 100).json()["authorization_id"]
    api.void(world.tok["dee"], closed)
    authz_page(page, "ada@example.com")
    expect(tid(page, f"authorization-item-{inc}")).to_be_visible()
    expect(tid(page, f"authorization-capture-amount-{inc}")).to_have_value("15.50")
    for name, n in ((f"authorization-capture-{inc}", 1), (f"authorization-void-{inc}", 0),
                    (f"authorization-void-{out}", 1), (f"authorization-capture-{out}", 0),
                    (f"authorization-capture-amount-{out}", 0),
                    (f"authorization-capture-{closed}", 0),
                    (f"authorization-capture-amount-{closed}", 0)):
        expect(tid(page, name)).to_have_count(n)


def test_R2_AUI_18_capture_from_ui_partial(world, api, page):
    wire = Wire(page)
    aid = api.authorize(world.tok["dee"], "ada", 2000).json()["authorization_id"]
    authz_page(page, "ada@example.com")
    tid(page, f"authorization-capture-amount-{aid}").fill("15.00")
    tid(page, f"authorization-capture-{aid}").click()
    expect(tid(page, f"authorization-item-{aid}")).to_have_attribute("data-status", "captured")
    expect(tid(page, f"authorization-captured-{aid}")).to_have_text("15.00 EUR")
    sent = wire.to(f"/authorizations/{aid}/capture")
    assert sent[0]["body"]["amount"] == 1500 and sent[0]["key"]
    m = world.me("dee")
    assert (m["total"], m["held"], m["available"]) == (3500, 0, 3500)


def test_R2_AUI_14_void_from_ui(world, api, page):
    aid = api.authorize(world.tok["ada"], "bob", 2000).json()["authorization_id"]
    authz_page(page, "ada@example.com")
    tid(page, f"authorization-void-{aid}").click()
    expect(tid(page, f"authorization-item-{aid}")).to_have_attribute("data-status", "voided")
    expect(tid(page, f"authorization-void-{aid}")).to_have_count(0)
    assert world.me("ada")["held"] == 0


def test_R2_AUI_15_capture_refused_shows_error(make_world, api, page):
    w = make_world(fixture(authorization_ttl_seconds=3))
    aid = api.authorize(w.tok["dee"], "ada", 2000).json()["authorization_id"]
    authz_page(page, "ada@example.com")
    expect(tid(page, f"authorization-capture-{aid}")).to_be_visible()
    time.sleep(3.5)                                  # it expires behind the open page
    tid(page, f"authorization-capture-{aid}").click()
    expect(tid(page, "authorization-error")).to_be_visible()


# ---------------------------------------------------------------- quality

LONG_NOTE = "x" * 200


def busy_world(make_world, api):
    users = [user("u_ada", "ada", 2 ** 50), user("u_abcdefghijklmnopqrst",
                                                  "abcdefghijklmnopqrst", 0)]
    w = make_world(fixture(users=users, settlement_operator_ids=[]))
    api.pay(w.tok["ada"], "abcdefghijklmnopqrst", 1_000_000_000, note=LONG_NOTE)
    api.request(w.tok["abcdefghijklmnopqrst"], "ada", 1_000_000_000, note=LONG_NOTE)
    api.authorize(w.tok["ada"], "abcdefghijklmnopqrst", 1_000_000_000, note=LONG_NOTE)
    return w


@pytest.mark.parametrize("width", [375, 390, 1280])
def test_R2_VIS_7_no_horizontal_scroll(make_world, api, new_page, width):
    busy_world(make_world, api)
    pg = new_page(width, 800)
    sign_in(pg, "ada@example.com")
    for route in ROUTES + ["/login", "/signup"]:
        goto(pg, route)
        pg.wait_for_timeout(500)
        sw = pg.evaluate("() => document.scrollingElement.scrollWidth")
        iw = pg.evaluate("() => window.innerWidth")
        assert sw <= iw, (route, width, sw, iw)


def test_R2_VIS_8_every_input_has_visible_label(world, new_page):
    pg = new_page(390, 844)
    goto(pg, "/signup")
    pg.wait_for_timeout(300)
    unlabeled = []
    for route in ["/signup", "/login", "/", "/split", "/authorizations"]:
        if route == "/":
            sign_in(pg, "ada@example.com")
        goto(pg, route)
        pg.wait_for_timeout(500)
        unlabeled += pg.evaluate("""(route) => [...document.querySelectorAll(
            'input:not([type=hidden]), select, textarea')].filter(el => {
              const vis = e => e && e.offsetParent !== null && e.innerText.trim().length > 0;
              const byFor = el.id && document.querySelector(`label[for="${el.id}"]`);
              const wrap = el.closest('label');
              const lb = el.getAttribute('aria-labelledby');
              const byAria = lb && document.getElementById(lb);
              return !(vis(byFor) || vis(wrap) || vis(byAria));
            }).map(el => route + ' ' + (el.dataset.testid || el.name || el.id))""", route)
    assert not unlabeled, unlabeled


def test_R2_VIS_9_focus_visible(world, new_page):
    pg = new_page(1280, 900)
    sign_in(pg, "ada@example.com")
    goto(pg, "/")
    pg.wait_for_timeout(500)
    missing = []
    for name in ("pay-handle", "pay-amount", "pay-submit", "wallet-refresh", "logout-button"):
        el = tid(pg, name)
        before = el.evaluate("e => { const s = getComputedStyle(e); return [s.outlineStyle, "
                             "s.outlineWidth, s.boxShadow, s.borderColor].join('|') }")
        el.focus()
        pg.keyboard.press("Shift+Tab")
        pg.keyboard.press("Tab")
        after = el.evaluate("e => { const s = getComputedStyle(e); return [s.outlineStyle, "
                            "s.outlineWidth, s.boxShadow, s.borderColor].join('|') }")
        if before == after or "none|0px|none" in after:
            missing.append((name, before, after))
    assert not missing, missing


CONTRAST_JS = """() => {
  const lum = c => { const m = c.match(/[\\d.]+/g).map(Number);
    const [r,g,b] = m.slice(0,3).map(v => { v /= 255;
      return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); });
    return 0.2126*r + 0.7152*g + 0.0722*b; };
  const bg = el => { for (let e = el; e; e = e.parentElement) {
      const c = getComputedStyle(e).backgroundColor;
      const m = c.match(/[\\d.]+/g); if (m && (m.length < 4 || +m[3] > 0.5)) return c; }
    return 'rgb(255,255,255)'; };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!el.offsetParent || !el.childNodes.length) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || +s.opacity === 0) continue;
    const L1 = lum(s.color), L2 = lum(bg(el));
    const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const size = parseFloat(s.fontSize), bold = +s.fontWeight >= 700;
    const need = (size >= 24 || (bold && size >= 18.66)) ? 3 : 4.5;
    if (ratio < need) bad.push([el.tagName, (el.dataset.testid||''), el.textContent.trim().slice(0,30), ratio.toFixed(2)]);
  }
  return bad; }"""


def test_R2_VIS_10_text_contrast_wcag_aa(world, api, new_page):
    api.pay(world.tok["ada"], "bob", 100)
    api.request(world.tok["bob"], "ada", 100)
    pg = new_page(1280, 900)
    goto(pg, "/login")
    pg.wait_for_timeout(300)
    bad = pg.evaluate(CONTRAST_JS)
    sign_in(pg, "ada@example.com")
    for route in ROUTES:
        goto(pg, route)
        pg.wait_for_timeout(600)
        bad += [[route] + b for b in pg.evaluate(CONTRAST_JS)]
    assert not bad, bad[:10]


def test_R2_SCR_8_no_external_requests(world, new_page):
    pg = new_page(1280, 900)
    foreign = []
    pg.on("request", lambda r: foreign.append(r.url) if not r.url.startswith(TARGET_URL)
          and not r.url.startswith("data:") else None)
    sign_in(pg, "ada@example.com")
    for route in ROUTES:
        goto(pg, route)
        pg.wait_for_timeout(400)
    assert not foreign, foreign


def test_R2_VIS_2_AUI_3_available_is_headline(make_world, new_page):
    make_world(authorizations=[auth_rec("a_1", "u_ada", "u_bob", 2000)])
    pg = new_page(390, 844)
    open_wallet(pg, "ada@example.com")
    size = {n: tid(pg, n).evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
            for n in ("wallet-available", "wallet-balance", "wallet-held")}
    assert size["wallet-available"] > size["wallet-balance"], size
    assert size["wallet-available"] > size["wallet-held"], size
    # and it is the largest monetary figure on the page
    biggest = pg.evaluate("""() => Math.max(...[...document.querySelectorAll(
        '[data-testid^="activity-amount-"],[data-testid^="wallet-"]')].map(
        e => parseFloat(getComputedStyle(e).fontSize)))""")
    assert size["wallet-available"] >= biggest


def test_R2_VIS_12_navigation_consistent(world, new_page):
    pg = new_page(1280, 900)
    sign_in(pg, "ada@example.com")
    navs = []
    for route in ROUTES:
        goto(pg, route)
        pg.wait_for_timeout(400)
        navs.append(tuple(pg.evaluate("""() => [...document.querySelectorAll('nav a[href]')]
            .map(a => a.getAttribute('href'))""")))
    assert navs[0] and all(n == navs[0] for n in navs), navs
    for r in ROUTES:
        assert r in navs[0]


def test_R2_VIS_5_states_visually_distinct(world, api, new_page):
    pg = new_page(1280, 900)
    open_wallet(pg, "ada@example.com")
    tid(pg, "pay-handle").fill("nobody")
    tid(pg, "pay-amount").fill("1")
    tid(pg, "pay-submit").click()
    expect(tid(pg, "pay-error")).to_be_visible()
    err = tid(pg, "pay-error").evaluate("e => [getComputedStyle(e).color, "
                                        "getComputedStyle(e).backgroundColor].join()")
    state = {"n": 0}

    def lose(route):
        state["n"] += 1
        route.abort("failed")

    pg.route("**/payments", lose)
    tid(pg, "pay-handle").fill("bob")
    tid(pg, "pay-submit").click()
    expect(tid(pg, "pay-uncertain")).to_be_visible()
    unc = tid(pg, "pay-uncertain").evaluate("e => [getComputedStyle(e).color, "
                                            "getComputedStyle(e).backgroundColor].join()")
    assert err != unc, (err, unc)
