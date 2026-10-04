"""Playwright helpers: the UI is driven only through the spec's data-testid names."""
import json
from urllib.parse import urlparse

from playwright.sync_api import expect

from s2lib import PASSWORD, TARGET_URL

VIEWPORTS = {"mobile": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}
API_PATHS = ("/payments", "/requests", "/splits", "/authorizations", "/settlements")


def T(name):
    return f'[data-testid="{name}"]'


def tid(page, name):
    return page.locator(T(name))


def goto(page, path):
    page.goto(TARGET_URL + path)


def sign_in(page, email, password=PASSWORD):
    goto(page, "/login")
    tid(page, "login-email").fill(email)
    tid(page, "login-password").fill(password)
    tid(page, "login-submit").click()
    expect(tid(page, "current-user")).to_be_visible()


def open_wallet(page, email):
    sign_in(page, email)
    goto(page, "/")
    expect(tid(page, "wallet-balance")).to_be_visible()


def path_of(url):
    return urlparse(url).path


class Wire:
    """Records every API write the page sends (method, path, idempotency key, JSON body)."""

    def __init__(self, page):
        self.writes = []
        page.on("request", self._on)

    def _on(self, req):
        if req.method != "POST":
            return
        p = path_of(req.url)
        if not p.startswith(API_PATHS):
            return
        try:
            body = json.loads(req.post_data or "null")
        except ValueError:
            body = req.post_data
        self.writes.append({"path": p, "key": req.headers.get("idempotency-key"), "body": body})

    def to(self, path_prefix):
        return [w for w in self.writes if w["path"].startswith(path_prefix)]


def fill_pay(page, handle, amount, note="", visibility=None):
    tid(page, "pay-handle").fill(handle)
    tid(page, "pay-amount").fill(amount)
    tid(page, "pay-note").fill(note)
    if visibility:
        tid(page, "pay-visibility").select_option(visibility)


def text(page, name):
    return tid(page, name).inner_text().strip()
