#!/usr/bin/env python3
"""Browser checks for the stage 2 UI (designer lane). Needs a running service and Playwright.

    TARGET_URL=http://127.0.0.1:18300 python stage-2/tools/ui_check.py auth [units wallet ...]

Each check runs at 390 and 1280 px, fails on console errors, page errors, 5xx responses and
horizontal page scrolling, and saves screenshots under reviews/stage2/shots/<check>/<width>/.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("TARGET_URL", "http://127.0.0.1:18300").rstrip("/")
ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "reviews" / "stage2" / "shots"
WIDTHS = (390, 1280)
PASSWORD = "correct horse"
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  FAIL", msg)
    return cond


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def reset(users=None, **extra):
    users = users or [
        {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob", "handle": "bob", "balance": 2500},
    ]
    assert post("/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users, **extra}) == 204


class Page:
    """A page wrapper that records console errors, page errors and 5xx responses."""

    def __init__(self, browser, width, height=800):
        self.ctx = browser.new_context(viewport={"width": width, "height": height})
        self.page = self.ctx.new_page()
        self.problems = []
        # Chromium logs every 4xx fetch as a console error; refusals are expected, so only other errors count.
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}")
                     if m.type in ("error", "warning") and "status of 4" not in m.text else None)
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("response", lambda r: self.problems.append(f"{r.status} {r.url}") if r.status >= 500 else None)
        self.width = width

    def t(self, testid):
        return self.page.get_by_test_id(testid)

    def wait_attr(self, testid, name, value):
        expect(self.t(testid)).to_have_attribute(name, value)

    def wait_text(self, testid, value):
        expect(self.t(testid)).to_have_text(value)

    def no_hscroll(self, label):
        sw = self.page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        check(sw[0] <= sw[1], f"{label} @{self.width}: horizontal scroll {sw}")

    def shot(self, check_name, name):
        d = SHOTS / check_name / str(self.width)
        d.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(d / f"{name}.png"), full_page=True)

    def focus_visible(self, label):
        """Tab through the page; every focused element must show an outline or ring."""
        seen = 0
        for _ in range(14):
            self.page.keyboard.press("Tab")
            info = self.page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null;
                const s = getComputedStyle(e); return {tag: e.tagName, ow: parseFloat(s.outlineWidth), os: s.outlineStyle}; }""")
            if info:
                seen += 1
                check(info["os"] != "none" and info["ow"] >= 2, f"{label} @{self.width}: no visible focus ring on {info['tag']}")
        check(seen >= 4, f"{label} @{self.width}: tab reached only {seen} controls")

    def done(self, label):
        for p in self.problems:
            check(False, f"{label} @{self.width}: {p}")
        self.ctx.close()


def check_auth(browser):
    for width in WIDTHS:
        reset()
        pg = Page(browser, width)
        page = pg.page
        # signed out: every guarded route sends us to /login
        for route in ("/", "/requests", "/split", "/authorizations"):
            page.goto(BASE + route)
            page.wait_for_url("**/login")
        check(page.locator("[data-testid=login-email]").is_visible(), "login email visible")
        pg.shot("auth", "login")
        pg.no_hscroll("login")
        pg.focus_visible("login")

        # wrong password -> auth-error present, then removed on input
        pg.t("login-email").fill("ada@example.com")
        pg.t("login-password").fill("wrong horse!")
        pg.t("login-submit").click()
        pg.t("auth-error").wait_for()
        check(pg.t("auth-error").count() == 1, "one auth-error")
        pg.shot("auth", "login-error")
        pg.t("login-email").fill("ada@example.com")
        check(pg.t("auth-error").count() == 0, "auth-error disappears on input")

        # correct login -> / with current-user and exact handle
        pg.t("login-password").fill(PASSWORD)
        pg.t("login-submit").click()
        page.wait_for_url(BASE + "/")
        pg.t("current-user").wait_for()
        check("Ada" in pg.t("current-user").inner_text(), "current-user has the display name")
        check(pg.t("current-handle").text_content() == "ada", f"current-handle exact: {pg.t('current-handle').text_content()!r}")
        for route in ("/", "/requests", "/split", "/authorizations"):
            page.goto(BASE + route)
            pg.t("current-user").wait_for()
            check(pg.t("current-handle").text_content() == "ada", f"current-handle on {route}")
            check(page.locator("nav[aria-label=Main] a[aria-current=page], .tabbar a[aria-current=page]").count() >= 1, f"active nav on {route}")
            pg.no_hscroll(route)
        pg.shot("auth", "signed-in-shell")

        # token survives a reload; logout clears it
        page.reload()
        pg.t("current-user").wait_for()
        pg.t("logout-button").click()
        page.wait_for_url("**/login")
        check(page.evaluate("localStorage.getItem('pocketful.token')") is None, "token cleared on logout")

        # signup: new account lands signed in; duplicate email -> auth-error
        page.goto(BASE + "/signup")
        pg.t("signup-display-name").fill("Zed Zebra")
        pg.t("signup-email").fill("zed@example.com")
        pg.t("signup-password").fill("longenough1")
        pg.shot("auth", "signup")
        pg.no_hscroll("signup")
        pg.t("signup-submit").click()
        page.wait_for_url(BASE + "/")
        check(pg.t("current-handle").text_content() == "zed", "signup handle derived from email")
        pg.t("logout-button").click()
        page.goto(BASE + "/signup")
        pg.t("signup-display-name").fill("Zed Again")
        pg.t("signup-email").fill("zed@example.com")
        pg.t("signup-password").fill("longenough1")
        pg.t("signup-submit").click()
        pg.t("auth-error").wait_for()
        pg.shot("auth", "signup-error")
        page.goto(BASE + "/signup")
        pg.t("signup-display-name").fill("Short")
        pg.t("signup-email").fill("short@example.com")
        pg.t("signup-password").fill("tiny")
        pg.t("signup-submit").click()
        pg.t("auth-error").wait_for()
        check(pg.t("auth-error").count() == 1, "short password refused")
        pg.done("auth")


def login(pg, email="ada@example.com"):
    pg.page.goto(BASE + "/login")
    pg.t("login-email").fill(email)
    pg.t("login-password").fill(PASSWORD)
    pg.t("login-submit").click()
    pg.t("current-user").wait_for()


def api_json(path, token=None, method="GET", body=None, key=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def check_units(browser):
    pg = Page(browser, 390)
    page = pg.page
    page.goto(BASE + "/login")
    r = page.evaluate("""async () => {
      const m = await import('/assets/js/money.js'); const i = await import('/assets/js/idem.js'); const f = await import('/assets/js/refresh.js');
      const out = {};
      out.shares = [[1000,3],[1,3],[10,3],[999,3],[5,5]].map(([a,n]) => m.splitShares(a,n).map(String));
      const parse = (t, mu) => { const r = m.parseAmount(t, mu); return r.error || String(r.minor); };
      out.parse2 = ['15','15.00','15.5','15.005','abc','','-1','1e3','.5','1.','1,5',' 7 ','0','007.10'].map(t => parse(t, 2));
      out.parse0 = ['1200','12.0','12.5'].map(t => parse(t, 0));
      out.parse3 = ['1.234','1.2345','2'].map(t => parse(t, 3));
      out.fmt = [m.formatAmount(10000,2,'EUR'), m.formatAmount(1200,0,'JPY'), m.formatAmount(1234,3,'BHD'), m.formatAmount(5,2,'EUR'), m.formatAmount(0,2,'EUR'),
                 m.formatAmount(9007199254740992n,2,'EUR'), m.formatAmount(123456789012,2,'EUR')];
      const a = new i.Attempt('/payments'); const body = {to_handle:'bob', amount:1500, note:'', visibility:'public'};
      const p1 = a.prepare(body); a.begin(); a.uncertain();
      const p2 = a.prepare(body); a.begin(); a.succeeded();
      const p3 = a.prepare(body); const p4 = a.prepare({...body, amount:1600}); a.begin(); a.refused(); const p5 = a.prepare({...body, amount:1600});
      out.keys = {same_after_uncertain: p1.key === p2.key, skip_after_success: !!p3.skip, new_for_change: p4.key !== p1.key, new_after_refusal: p5.key !== p4.key,
                  keyorder: a.fingerprintOf({b:1,a:2}) === a.fingerprintOf({a:2,b:1})};
      const run = f.latestOnly(); const applied = [];
      const slow = run(() => new Promise(r => setTimeout(() => r('old'), 120)), v => applied.push(v));
      const fast = run(() => new Promise(r => setTimeout(() => r('new'), 10)), v => applied.push(v));
      const [s1, s2] = await Promise.all([slow, fast]);
      out.refresh = {applied, slowStale: s1.stale, fastStale: s2.stale};
      return out; }""")
    check(r["shares"] == [["334", "333", "333"], ["1", "0", "0"], ["4", "3", "3"], ["333", "333", "333"], ["1", "1", "1", "1", "1"]], f"§9 shares {r['shares']}")
    check(r["parse2"] == ["1500", "1500", "1550", "too_many_decimals", "not_a_number", "not_a_number", "not_a_number", "not_a_number", "not_a_number", "not_a_number", "not_a_number", "700", "0", "710"], f"parse2 {r['parse2']}")
    check(r["parse0"] == ["1200", "too_many_decimals", "too_many_decimals"], f"parse0 {r['parse0']}")
    check(r["parse3"] == ["1234", "too_many_decimals", "2000"], f"parse3 {r['parse3']}")
    check(r["fmt"] == ["100.00 EUR", "1200 JPY", "1.234 BHD", "0.05 EUR", "0.00 EUR", "90071992547409.92 EUR", "1234567890.12 EUR"], f"format {r['fmt']}")
    check(all(r["keys"].values()), f"key lifecycle {r['keys']}")
    check(r["refresh"] == {"applied": ["new"], "slowStale": True, "fastStale": False}, f"latest refresh wins {r['refresh']}")
    pg.done("units")


def check_wallet(browser):
    full = [
        {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": PASSWORD, "display_name": "Cy", "handle": "cy", "balance": 0},
    ]
    payments = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "coffee", "visibility": "public"},
                {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 1, "note": "", "visibility": "private"},
                {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 7, "note": "secret", "visibility": "private"}]
    for width in WIDTHS:
        reset(full, payments=payments)
        pg = Page(browser, width)
        page = pg.page
        posts = []
        page.on("request", lambda r: posts.append(r.post_data) if r.method == "POST" and r.url.endswith("/payments") else None)
        login(pg)
        pg.t("wallet-balance").wait_for()
        for tid in ("wallet-available", "wallet-balance", "wallet-refresh", "pay-handle", "pay-amount", "pay-note", "pay-visibility", "pay-submit",
                    "request-handle", "request-amount", "request-note", "request-submit", "authorize-handle", "authorize-submit", "activity-list",
                    "activity-item-p_1", "activity-item-p_2", "activity-parties-p_1", "activity-amount-p_1", "activity-note-p_1", "activity-note-p_2"):
            check(pg.t(tid).count() == 1, f"wallet @{width}: testid {tid} present once")
        check(pg.t("activity-item-p_3").count() == 0, "private payment between others is not shown")
        check(pg.t("wallet-balance").text_content() == "100.00 EUR", f"wallet-balance text {pg.t('wallet-balance').text_content()!r}")
        check(pg.t("wallet-balance").get_attribute("data-amount") == "10000", "wallet-balance data-amount")
        check(pg.t("wallet-held").count() == 0, "wallet-held absent when nothing is held")
        check(pg.t("activity-item-p_2").get_attribute("data-visibility") == "private", "data-visibility private")
        check(pg.t("activity-amount-p_1").text_content() == "5.00 EUR", "feed amount exact")
        check(pg.t("activity-note-p_2").text_content() == "", "empty note element present and empty")
        ids = page.eval_on_selector_all("[data-testid=activity-list] > li", "els => els.map(e => e.dataset.testid)")
        check(ids and ids[0].startswith("activity-item-"), f"feed order {ids}")
        sizes = page.evaluate("""() => { const f = e => parseFloat(getComputedStyle(document.querySelector(e)).fontSize);
            const all = [...document.querySelectorAll('main *')].filter(e => e.children.length === 0 && e.textContent.trim()).map(e => parseFloat(getComputedStyle(e).fontSize));
            return {hero: f('[data-testid=wallet-available]'), max: Math.max(...all)}; }""")
        check(sizes["hero"] >= sizes["max"], f"wallet-available is the largest text {sizes}")
        pg.no_hscroll("wallet")
        pg.shot("wallet", "loaded")

        # pay once; the unchanged form sends nothing the second time
        pg.t("pay-handle").fill("bob")
        pg.t("pay-amount").fill("15.00")
        pg.t("pay-note").fill("dinner")
        pg.t("pay-submit").click()
        pg.t("pay-success").wait_for()
        check(pg.t("wallet-balance").text_content() == "85.00 EUR", f"balance after pay {pg.t('wallet-balance').text_content()!r}")
        check(pg.t("pay-handle").input_value() == "bob" and pg.t("pay-amount").input_value() == "15.00", "pay form keeps its values")
        check(pg.t("pay-error").count() == 0, "no pay-error after success")
        count = page.locator("[data-testid=activity-list] > li").count()
        pg.shot("wallet", "pay-success")
        pg.t("pay-submit").click()
        pg.t("pay-already").wait_for()
        page.wait_for_timeout(300)
        check(len(posts) == 1, f"unchanged resubmit sent {len(posts)} POST /payments")
        check(pg.t("wallet-balance").text_content() == "85.00 EUR", "balance fell once")
        check(page.locator("[data-testid=activity-list] > li").count() == count, "one feed row for the payment")
        check(pg.t("pay-error").count() == 0, "no pay-error on unchanged resubmit")
        pg.t("pay-note").fill("dinner 2")
        pg.t("pay-submit").click()
        pg.t("pay-success").wait_for()
        pg.wait_text("wallet-balance", "70.00 EUR")
        check(len(posts) == 2, "a changed field is a new payment")

        # local validation: no request
        for bad in ("15.005", "abc", "-5", ""):
            pg.t("pay-amount").fill(bad)
            pg.t("pay-submit").click()
            pg.t("pay-error").wait_for()
        check(len(posts) == 2, "invalid amounts send no request")
        pg.shot("wallet", "pay-invalid")

        # refused: insufficient funds; inputs kept, error shown, balance refreshed
        pg.t("pay-amount").fill("1000.00")
        pg.t("pay-submit").click()
        pg.t("pay-error").wait_for()
        check(pg.t("pay-handle").input_value() == "bob" and pg.t("pay-amount").input_value() == "1000.00" and pg.t("pay-note").input_value() == "dinner 2", "inputs preserved after refusal")
        check("Not enough" in pg.t("pay-error").inner_text(), "pay-error says why")
        pg.shot("wallet", "pay-refused")
        pg.t("pay-amount").fill("1.00")
        check(pg.t("pay-error").count() == 0, "pay-error clears when the form changes")

        # request form
        pg.t("request-handle").fill("cy")
        pg.t("request-amount").fill("3.50")
        pg.t("request-submit").click()
        pg.t("request-success").wait_for()
        st, body = api_json("/requests", token=api_json("/auth/login", method="POST", body={"email": "cy@example.com", "password": PASSWORD})[1]["token"])
        check(st == 200 and any(q["amount"] == 350 for q in body["requests"]), f"request created {body}")
        pg.t("request-handle").fill("nobody")
        pg.t("request-amount").fill("1")
        pg.t("request-submit").click()
        pg.t("request-error").wait_for()

        # refresh button leaves the form alone
        pg.t("pay-note").fill("keep me")
        pg.t("wallet-refresh").click()
        page.wait_for_timeout(300)
        check(pg.t("pay-note").input_value() == "keep me", "refresh keeps form values")
        pg.focus_visible("wallet")
        pg.done("wallet")

        # empty feed and a JPY wallet
        reset([{"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 1200}], currency="JPY", minor_units=0)
        pg = Page(browser, width)
        login(pg)
        pg.t("wallet-balance").wait_for()
        check(pg.t("wallet-balance").text_content() == "1200 JPY", f"JPY format {pg.t('wallet-balance').text_content()!r}")
        pg.t("empty-activity").wait_for()
        check(pg.t("activity-list").count() == 0, "no list when empty")
        pg.t("pay-handle").fill("x")
        pg.t("pay-amount").fill("1.5")
        pg.t("pay-submit").click()
        pg.t("pay-error").wait_for()
        pg.shot("wallet", "empty-jpy")
        pg.done("wallet-jpy")
        # the largest allowed balance fits on one line
        reset([{"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 9007199254740992}])
        pg = Page(browser, width)
        login(pg)
        pg.t("wallet-balance").wait_for()
        pg.no_hscroll("max balance")
        box = pg.t("wallet-available").bounding_box()
        lines = pg.page.evaluate("(() => { const e = document.querySelector('[data-testid=wallet-available]'); const r = document.createRange(); r.selectNodeContents(e); return new Set([...r.getClientRects()].map(x => Math.round(x.top))).size; })()")
        check(lines == 1, f"max balance on one line @{width}: {lines} lines, box {box}")
        pg.shot("wallet", "max-balance")
        pg.done("wallet-max")


def token_for(email):
    return api_json("/auth/login", method="POST", body={"email": email, "password": PASSWORD})[1]["token"]


def check_requests(browser):
    users = [
        {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": PASSWORD, "display_name": "Cy", "handle": "cy", "balance": 0},
    ]
    def rq(i, req, payer, amount, status="pending", note=""):
        return {"id": i, "requester_id": req, "payer_id": payer, "amount": amount, "note": note, "status": status}
    requests = [rq("rq_in", "u_bob", "u_ada", 1200, note="taxi"), rq("rq_pay", "u_bob", "u_ada", 300, note="lunch"),
                rq("rq_dec", "u_cy", "u_ada", 50), rq("rq_out", "u_ada", "u_cy", 99999, note="rent"),
                rq("rq_done", "u_bob", "u_ada", 300, "declined", "old")]
    for width in WIDTHS:
        reset(users, requests=requests)
        pg = Page(browser, width)
        page = pg.page
        login(pg)
        page.goto(BASE + "/requests")
        pg.t("incoming-list").wait_for()
        pg.t("request-item-rq_in").wait_for()
        for tid in ("incoming-list", "outgoing-list", "request-item-rq_in", "request-item-rq_out", "request-item-rq_done", "request-amount-rq_in", "request-pay-rq_in",
                    "request-decline-rq_in", "request-cancel-rq_out"):
            check(pg.t(tid).count() == 1, f"requests @{width}: {tid} present once")
        check(pg.t("request-item-rq_in").get_attribute("data-status") == "pending", "pending status")
        check(pg.t("request-item-rq_done").get_attribute("data-status") == "declined", "declined status")
        check(pg.t("request-amount-rq_in").text_content() == "12.00 EUR", "request amount exact")
        check(pg.t("request-amount-rq_out").text_content() == "999.99 EUR", "long amount exact")
        for tid in ("request-cancel-rq_in", "request-pay-rq_out", "request-decline-rq_out", "request-pay-rq_done", "request-decline-rq_done", "request-cancel-rq_done", "request-error", "empty-requests"):
            check(pg.t(tid).count() == 0 or not pg.t(tid).is_visible(), f"requests @{width}: {tid} absent")
        in_ids = page.eval_on_selector_all("[data-testid=incoming-list] [data-testid^=request-item-]", "e => e.map(x => x.dataset.testid)")
        check("request-item-rq_out" not in in_ids and "request-item-rq_in" in in_ids, f"incoming list contents {in_ids}")
        pg.no_hscroll("requests")
        pg.shot("requests", "loaded")

        # cancelled elsewhere while the pay button is visible -> request-error, stale button disappears
        bob = token_for("bob@example.com")
        st, _ = api_json("/requests/rq_in/cancel", token=bob, method="POST")
        check(st == 200, "bob cancels rq_in elsewhere")
        pg.t("request-pay-rq_in").click()
        pg.t("request-error").wait_for()
        pg.t("request-item-rq_in").wait_for()
        pg.wait_attr('request-item-rq_in', 'data-status', 'cancelled')
        check(pg.t("request-pay-rq_in").count() == 0, "stale pay button disappears")
        check("no longer pending" in pg.t("request-error").inner_text(), "request-error names the cause")
        pg.shot("requests", "stale-refused")

        # pay moves money once and shows paid
        before = api_json("/me", token=token_for("ada@example.com"))[1]["balance"]
        pg.t("request-pay-rq_pay").click()
        pg.wait_attr('request-item-rq_pay', 'data-status', 'paid')
        after = api_json("/me", token=token_for("ada@example.com"))[1]["balance"]
        check(before - after == 300, f"pay moved {before - after}")
        check(pg.t("request-pay-rq_pay").count() == 0, "no pay button once paid")
        check(pg.t("request-paid").count() == 1, "paid confirmation after refresh")
        chip = page.locator("[data-chip=balance] b").text_content()
        check(chip is not None and chip.startswith("97.00") or chip.startswith("9700"), f"header balance chip refreshed: {chip}")

        pg.t("request-decline-rq_dec").click()
        pg.wait_attr('request-item-rq_dec', 'data-status', 'declined')
        pg.t("request-cancel-rq_out").click()
        pg.wait_attr('request-item-rq_out', 'data-status', 'cancelled')
        check(pg.t("request-cancel-rq_out").count() == 0, "no cancel button once cancelled")
        pg.shot("requests", "after-actions")
        pg.focus_visible("requests")
        pg.done("requests")

        reset([users[2]], requests=[])
        pg = Page(browser, width)
        login(pg, "cy@example.com")
        pg.page.goto(BASE + "/requests")
        pg.t("empty-requests").wait_for()
        check(pg.t("empty-requests").is_visible(), "empty-requests visible")
        pg.shot("requests", "empty")
        pg.done("requests-empty")


def check_split(browser):
    users = [
        {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD, "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD, "display_name": "Bob", "handle": "bob", "balance": 0},
        {"id": "u_cy", "email": "cy@example.com", "password": PASSWORD, "display_name": "Cy", "handle": "cy", "balance": 0},
    ]
    rows = [("10.00", "ada, bob, cy", ["3.34 EUR", "3.33 EUR", "3.33 EUR"]), ("0.01", "ada,bob,cy", ["0.01 EUR", "0.00 EUR", "0.00 EUR"]),
            ("0.10", "bob, cy, ada", ["0.04 EUR", "0.03 EUR", "0.03 EUR"]), ("9.99", "ada, bob, cy", ["3.33 EUR"] * 3), ("0.05", "a, b, c, d, e", ["0.01 EUR"] * 5)]
    for width in WIDTHS:
        reset(users)
        pg = Page(browser, width)
        page = pg.page
        posts = []
        page.on("request", lambda r: posts.append(r.post_data) if r.method == "POST" and r.url.endswith("/splits") else None)
        login(pg)
        page.goto(BASE + "/split")
        pg.t("split-amount").wait_for()
        check(pg.t("split-preview").count() == 1, "split-preview present")
        for amount, handles, want in rows:
            pg.t("split-amount").fill(amount)
            pg.t("split-handles").fill(handles)
            names = [h.strip().lstrip("@") for h in handles.split(",")]
            for name, share in zip(names, want):
                check(pg.t(f"split-share-{name}").text_content() == share, f"split @{width} {amount}/{handles}: {name} {pg.t(f'split-share-{name}').text_content()!r} != {share}")
        check(len(posts) == 0, "preview sends nothing")
        pg.t("split-amount").fill("10.00")
        pg.t("split-handles").fill("ada, bob, cy")
        pg.t("split-note").fill("dinner")
        preview = [pg.t(f"split-share-{n}").text_content() for n in ("ada", "bob", "cy")]
        pg.shot("split", "preview")
        pg.t("split-submit").click()
        pg.t("split-success").wait_for()
        check(len(posts) == 1, "one POST /splits")
        st, body = api_json("/requests", token=token_for("bob@example.com"))
        got = [f"{q['amount'] // 100}.{q['amount'] % 100:02d} EUR" for q in body["requests"]]
        check(got == [preview[1]], f"server share for bob {got} == preview {preview[1]}")
        pg.shot("split", "success")
        pg.t("split-submit").click()
        pg.t("split-already").wait_for()
        page.wait_for_timeout(200)
        check(len(posts) == 1, "unchanged resubmit sends nothing")
        # caller omitted, only the caller, unknown handle, invalid input
        pg.t("split-handles").fill("bob, cy")
        check([pg.t("split-share-bob").text_content(), pg.t("split-share-cy").text_content()] == ["5.00 EUR", "5.00 EUR"], "caller omitted: n = listed handles")
        pg.t("split-handles").fill("ada")
        check(pg.t("split-share-ada").text_content() == "10.00 EUR", "caller only")
        pg.t("split-submit").click()
        pg.t("split-success").wait_for()
        pg.t("split-handles").fill("ada, nobody")
        pg.t("split-submit").click()
        pg.t("split-error").wait_for()
        pg.shot("split", "error")
        n = len(posts)
        pg.t("split-amount").fill("1.005")
        pg.t("split-submit").click()
        pg.t("split-error").wait_for()
        check(len(posts) == n, "invalid amount sends nothing")
        check(pg.t("split-share-ada").count() == 0, "no shares for an invalid amount")
        pg.no_hscroll("split")
        pg.focus_visible("split")
        pg.done("split")


CHECKS = {"auth": check_auth, "units": check_units, "wallet": check_wallet, "requests": check_requests, "split": check_split}


def main():
    names = sys.argv[1:] or list(CHECKS)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in names:
            print(f"== {name}")
            CHECKS[name](browser)
        browser.close()
    print("FAILED" if FAILS else "OK", len(FAILS), "findings")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
