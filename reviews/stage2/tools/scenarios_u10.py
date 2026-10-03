"""Verifier scenarios for S2.U10: dirty-form keys, split parsing, list containers, refresh supersede.

    $PY reviews/stage2/tools/scenarios_u10.py http://127.0.0.1:<port> [width]
"""
import json
import sys
import urllib.request

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


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h.title(), "handle": h, "balance": b}


def reset():
    assert api("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                                         "users": [U("u_ada", "ada", 10000), U("u_bob", "bob", 0), U("u_cy", "cy", 0)]})[0] == 204
    return api("POST", "/auth/login", {"email": "ada@e.com", "password": "correct horse"})[1]["token"]


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


def login(browser, route="/"):
    page = browser.new_page(viewport={"width": W, "height": 900})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(B + "/login")
    page.fill(T("login-email"), "ada@e.com"); page.fill(T("login-password"), "correct horse"); page.click(T("login-submit"))
    page.wait_for_selector(T("current-user"))
    if route != "/":
        page.goto(B + route)
    page.wait_for_load_state("networkidle")
    return page, errs


with sync_playwright() as p:
    browser = p.chromium.launch()

    tok = reset()
    page, errs = login(browser)
    posts = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/payments") and posts.append(r.headers.get("idempotency-key")))
    page.fill(T("pay-handle"), "bob"); page.fill(T("pay-amount"), "1"); page.fill(T("pay-note"), "x")
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    page.click(T("pay-submit")); page.wait_for_timeout(400)
    unchanged_ok = len(posts) == 1
    page.fill(T("pay-note"), "y"); page.fill(T("pay-note"), "x")       # edit, then revert
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-success")); page.wait_for_timeout(300)
    check("unchanged resubmit sends nothing; edit-then-revert is a new payment with a new key",
          unchanged_ok and len(posts) == 2 and posts[0] != posts[1] and api("GET", "/me", tok=tok)[1]["total"] == 9800, str(posts))
    # uncertain then unchanged retry keeps the key
    page.route("**/payments", lambda route: (route.fetch(), route.abort()))
    page.fill(T("pay-amount"), "2"); page.click(T("pay-submit")); page.wait_for_selector(T("pay-uncertain"))
    page.unroute("**/payments")
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    check("after an unknown outcome an unchanged retry reuses the key; money once", posts[2] == posts[3]
          and api("GET", "/me", tok=tok)[1]["total"] == 9600, str(posts[2:]))
    # refresh can be superseded while held
    held = []
    page.route("**/me", lambda route: held.append(route) if len(held) == 0 else route.continue_())
    page.click(T("wallet-refresh")); page.wait_for_timeout(300)
    enabled = page.is_enabled(T("wallet-refresh"))
    api("POST", "/payments", {"to_handle": "bob", "amount": 100}, tok, "elsewhere")
    page.click(T("wallet-refresh"))
    for _ in range(50):
        if page.inner_text(T("wallet-balance")).strip() == "95.00 EUR":
            break
        page.wait_for_timeout(100)
    if held:
        held[0].continue_()
    page.wait_for_timeout(800)
    check("wallet-refresh stays enabled while a refresh is held; newer read wins over the late older one",
          enabled and page.inner_text(T("wallet-balance")).strip() == "95.00 EUR" and page.input_value(T("pay-amount")) == "2")
    page.unroute("**/me")
    check("no page errors (wallet)", not errs, str(errs))
    page.close()

    # split parsing
    reset()
    page, errs = login(browser, "/split")
    sposts = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/splits") and sposts.append(r.post_data))
    bad = {}
    for text in ("ada,,bob", "ada, bob,", ",ada", "ada, ,bob"):
        page.fill(T("split-amount"), "10"); page.fill(T("split-handles"), text)
        shares = page.locator('[data-testid^="split-share-"]').count()
        page.click(T("split-submit")); page.wait_for_selector(T("split-error"))
        bad[text] = shares
    check("empty segments -> split-error, no shares, no POST", not sposts and all(v == 0 for v in bad.values()), str(bad))
    page.fill(T("split-handles"), " ada , bob,cy ")
    got = [page.inner_text(T("split-share-" + h)).strip() for h in ("ada", "bob", "cy")]
    page.click(T("split-submit")); page.wait_for_selector(T("split-success"))
    body = json.loads(sposts[-1])
    check("whitespace trimmed, order kept", got == ["3.34 EUR", "3.33 EUR", "3.33 EUR"] and body["participant_handles"] == ["ada", "bob", "cy"], str(body))
    page.close()

    # requests: containers kept when empty
    reset()
    page, errs = login(browser, "/requests")
    page.wait_for_selector(T("empty-requests"))
    check("empty-requests visible and both list containers present once",
          page.locator(T("incoming-list")).count() == 1 and page.locator(T("outgoing-list")).count() == 1 and page.locator(T("empty-requests")).is_visible())
    page.close()
    browser.close()

sys.exit(0 if all(results) else 1)
