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

from playwright.sync_api import sync_playwright

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


CHECKS = {"auth": check_auth}


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
