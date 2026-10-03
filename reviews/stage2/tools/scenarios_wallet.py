"""Verifier behavioural scenarios for the wallet screen `/` (stage 2 U2/U3), independent of the designer's ui_check.

    PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
    $PY reviews/stage2/tools/scenarios_wallet.py http://127.0.0.1:<port> [width]
Prints one line per scenario and exits 1 if any fails.
"""
import json
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

B = sys.argv[1].rstrip("/")
W = int(sys.argv[2]) if len(sys.argv) > 2 else 390
T = lambda t: '[data-testid="%s"]' % t


def api(method, path, body=None, tok=None, key=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    if key:
        h["Idempotency-Key"] = key
    req = urllib.request.Request(B + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = r.read()
            return r.status, json.loads(d) if d else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h.title(),
                     "handle": h, "balance": b}


def reset(ada=10000, auths=(), currency="EUR", mu=2):
    assert api("POST", "/_test/reset", {"currency": currency, "minor_units": mu,
                                         "users": [U("u_ada", "ada", ada), U("u_bob", "bob", 0)],
                                         "authorizations": list(auths)})[0] == 204
    return api("POST", "/auth/login", {"email": "ada@e.com", "password": "correct horse"})[1]["token"]


def total(tok):
    return api("GET", "/me", tok=tok)[1]["total"]


def login_page(browser):
    page = browser.new_page(viewport={"width": W, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(B + "/login")
    page.fill(T("login-email"), "ada@e.com")
    page.fill(T("login-password"), "correct horse")
    page.click(T("login-submit"))
    page.wait_for_selector(T("wallet-available"))
    return page, errors


def count_posts(page, path="/payments"):
    seen = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith(path) and seen.append(r.headers.get("idempotency-key")))
    return seen


def fill_pay(page, handle="bob", amount="15.00", note="dinner"):
    page.fill(T("pay-handle"), handle)
    page.fill(T("pay-amount"), amount)
    page.fill(T("pay-note"), note)


def text(page, tid):
    loc = page.locator(T(tid))
    return loc.first.inner_text().strip() if loc.count() else None


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


with sync_playwright() as p:
    browser = p.chromium.launch()

    # 1. pay once, unchanged resubmit sends nothing; changed note sends a new one
    tok = reset()
    page, errs = login_page(browser)
    posts = count_posts(page)
    fill_pay(page)
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    page.click(T("pay-submit")); page.wait_for_timeout(800)
    bal1 = total(tok)
    feed_rows = page.locator('[data-testid^="activity-item-"]').count()
    check("unchanged resubmit sends nothing", len(posts) == 1 and bal1 == 8500 and feed_rows == 1
          and text(page, "pay-error") is None and text(page, "wallet-balance") == "85.00 EUR",
          "posts=%d total=%d rows=%d balance=%s" % (len(posts), bal1, feed_rows, text(page, "wallet-balance")))
    check("form values kept after success", page.input_value(T("pay-handle")) == "bob" and page.input_value(T("pay-amount")) == "15.00")
    page.fill(T("pay-note"), "dinner 2"); page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    check("changed field sends a new payment with a new key", len(posts) == 2 and posts[0] != posts[1] and total(tok) == 7000)
    page.close()

    # 2. invalid amounts send nothing
    tok = reset()
    page, errs = login_page(browser)
    posts = count_posts(page)
    bad = []
    for amount in ("15.005", "abc", "-5", "", "1e3", "15,5"):
        fill_pay(page, amount=amount)
        page.click(T("pay-submit"))
        page.wait_for_timeout(150)
        bad.append((amount, text(page, "pay-error") is not None))
    check("invalid amounts show pay-error and send nothing", all(ok for _, ok in bad) and not posts, str(bad) + " posts=%d" % len(posts))
    fill_pay(page, amount="15.5"); page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    check("15.5 submits 1550", total(tok) == 10000 - 1550)
    page.close()

    # 3. lost response after commit, then retry with the same key and body
    tok = reset()
    page, errs = login_page(browser)
    posts = count_posts(page)

    def commit_then_drop(route):
        route.fetch()          # the server commits the payment
        route.abort()          # but the browser never sees the answer
    page.route("**/payments", commit_then_drop)
    fill_pay(page, amount="20")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-uncertain"))
    committed = total(tok)
    check("lost response shows pay-uncertain, not pay-error", text(page, "pay-error") is None and committed == 8000,
          "server total=%d" % committed)
    page.unroute("**/payments")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-success"))
    check("retry uses the same key; money moved once; uncertainty cleared",
          len(posts) == 2 and posts[0] == posts[1] and total(tok) == 8000 and text(page, "pay-uncertain") is None
          and text(page, "pay-error") is None and text(page, "wallet-balance") == "80.00 EUR",
          "keys=%s total=%d balance=%s" % (posts, total(tok), text(page, "wallet-balance")))
    page.close()

    # 4. competing client spends the balance; refused payment keeps inputs and refreshes
    tok = reset(ada=3000)
    page, errs = login_page(browser)
    api("POST", "/payments", {"to_handle": "bob", "amount": 2500}, tok, "other-client")
    fill_pay(page, amount="10", note="kept")
    page.click(T("pay-submit"))
    page.wait_for_selector(T("pay-error"))
    page.wait_for_timeout(500)
    check("refused payment: pay-error, inputs kept, balance refreshed",
          page.input_value(T("pay-amount")) == "10" and page.input_value(T("pay-note")) == "kept"
          and text(page, "wallet-balance") == "5.00 EUR" and page.locator('[data-testid^="activity-item-"]').count() == 1,
          "balance=%s" % text(page, "wallet-balance"))
    page.fill(T("pay-amount"), "4")
    check("pay-error clears on edit", text(page, "pay-error") is None)
    page.close()

    # 5. latest refresh wins with out-of-order responses
    tok = reset()
    page, errs = login_page(browser)
    gate = threading.Event()
    calls = {"n": 0}

    def slow_first(route):
        calls["n"] += 1
        if calls["n"] == 1:
            resp = route.fetch()            # read the OLD state now
            page.wait_for_timeout(1500)     # and answer late
            route.fulfill(response=resp)
        else:
            route.continue_()
    page.route("**/me", slow_first)
    fill_pay(page, amount="1", note="typed")
    page.click(T("wallet-refresh"))          # older read (slow, old state)
    page.wait_for_timeout(200)
    api("POST", "/payments", {"to_handle": "bob", "amount": 1000}, tok, "elsewhere")
    page.click(T("wallet-refresh"))          # newer read (fast, new state)
    page.wait_for_timeout(2500)
    check("latest refresh wins (old slow response ignored)", text(page, "wallet-balance") == "90.00 EUR"
          and page.input_value(T("pay-note")) == "typed", "balance=%s" % text(page, "wallet-balance"))
    page.unroute("**/me")
    page.close()

    # 6. holds: available is the headline, held shown, JPY format
    exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
    tok = reset(ada=1200, currency="JPY", mu=0, auths=[{"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                                                        "amount": 200, "status": "open", "expires_at": exp}])
    page, errs = login_page(browser)
    sizes = page.evaluate("""() => ['wallet-available','wallet-balance','wallet-held'].map(t => {
        const e = document.querySelector(`[data-testid="${t}"]`); return e ? parseFloat(getComputedStyle(e).fontSize) : null; })""")
    check("held: available headline, total and held secondary, JPY",
          text(page, "wallet-available") == "1000 JPY" and text(page, "wallet-balance") == "1200 JPY"
          and text(page, "wallet-held") == "200 JPY" and sizes[0] > max(sizes[1], sizes[2]),
          "texts=%s/%s/%s sizes=%s" % (text(page, "wallet-available"), text(page, "wallet-balance"), text(page, "wallet-held"), sizes))
    check("no page errors", not errs, str(errs))
    page.close()
    browser.close()

sys.exit(0 if all(ok for _, ok, _ in results) else 1)
