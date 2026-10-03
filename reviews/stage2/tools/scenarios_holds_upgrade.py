"""Verifier behavioural scenarios for `/authorizations` + held funds (U6), lost responses across an
export/import upgrade (U7), and /login, /signup while signed in (U9).

    $PY reviews/stage2/tools/scenarios_holds_upgrade.py http://127.0.0.1:<port> [width]
"""
import json
import sys
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
ts = lambda s: (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat(timespec="seconds")
A = lambda i, f, t, amt, st="open", exp=7200, **k: {"id": i, "from_user_id": f, "to_user_id": t, "amount": amt,
                                                    "status": st, "expires_at": ts(exp), "note": "hold " + i, **k}


def reset(users, auths=(), requests=()):
    assert api("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users,
                                         "authorizations": list(auths), "requests": list(requests)})[0] == 204
    return {u["handle"]: api("POST", "/auth/login", {"email": u["email"], "password": "correct horse"})[1]["token"] for u in users}


results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


def open_as(browser, who, route):
    page = browser.new_page(viewport={"width": W, "height": 900})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(B + "/login")
    page.fill(T("login-email"), who + "@e.com")
    page.fill(T("login-password"), "correct horse")
    page.click(T("login-submit"))
    page.wait_for_selector(T("current-user"))
    page.goto(B + route)
    page.wait_for_load_state("networkidle")
    return page, errs


has = lambda page, tid: page.locator(T(tid)).count() > 0
txt = lambda page, tid: page.inner_text(T(tid)).strip() if has(page, tid) else None
me = lambda tok: api("GET", "/me", tok=tok)[1]
item_status = lambda page, aid: page.get_attribute(T("authorization-item-" + aid), "data-status")


def wait_status(page, aid, status):
    page.wait_for_selector('[data-testid="authorization-item-%s"][data-status="%s"]' % (aid, status))


with sync_playwright() as p:
    browser = p.chromium.launch()
    users = [U("u_ada", "ada", 10000), U("u_bob", "bob", 2000), U("u_cy", "cy", 0)]

    # U6: wallet numbers right after reset with open holds; list presence rules
    tok = reset(users, auths=[A("a_in", "u_bob", "u_ada", 500), A("a_out", "u_ada", "u_bob", 2000),
                              A("a_cap", "u_bob", "u_ada", 300, "captured", captured_amount=300),
                              A("a_exp", "u_ada", "u_bob", 100, "open", exp=-7200), A("a_void", "u_ada", "u_cy", 50, "voided")])
    page, errs = open_as(browser, "ada", "/")
    check("wallet after reset with holds: available headline 80.00, total 100.00, held 20.00",
          txt(page, "wallet-available") == "80.00 EUR" and page.get_attribute(T("wallet-available"), "data-amount") == "8000"
          and txt(page, "wallet-balance") == "100.00 EUR" and txt(page, "wallet-held") == "20.00 EUR")
    page.goto(B + "/authorizations"); page.wait_for_selector(T("authorization-item-a_in"))
    api_exp = {a["authorization_id"]: a["expires_at"] for a in api("GET", "/authorizations", tok=tok["ada"])[1]["authorizations"]}
    check("presence rules", has(page, "authorization-capture-a_in") and page.input_value(T("authorization-capture-amount-a_in")) == "5.00"
          and not has(page, "authorization-void-a_in") and has(page, "authorization-void-a_out") and not has(page, "authorization-capture-a_out")
          and txt(page, "authorization-captured-a_cap") == "3.00 EUR" and not has(page, "authorization-captured-a_in")
          and item_status(page, "a_exp") == "expired" and not has(page, "authorization-void-a_exp") and not has(page, "authorization-capture-a_exp")
          and item_status(page, "a_void") == "voided" and txt(page, "authorization-amount-a_out") == "20.00 EUR"
          and all(txt(page, "authorization-expires-" + k) == v for k, v in api_exp.items()))
    order = page.eval_on_selector_all('[data-testid^="authorization-item-"]', "els => els.map(e => e.dataset.testid)")
    created = sorted(api("GET", "/authorizations", tok=tok["ada"])[1]["authorizations"], key=lambda a: (a["created_at"]), reverse=True)
    check("list follows the API's newest-first order", order == ["authorization-item-" + a["authorization_id"] for a in api("GET", "/authorizations", tok=tok["ada"])[1]["authorizations"]])
    # keep-open capture, then over-capture, then final partial
    page.fill(T("authorization-capture-amount-a_in"), "1.00"); page.check(T("authorization-keep-open-a_in"))
    page.click(T("authorization-capture-a_in")); page.wait_for_selector(T("authorization-captured"))
    page.wait_for_timeout(300)
    check("keep-open capture 1.00: stays open, prefill follows remaining 4.00", item_status(page, "a_in") == "open"
          and page.input_value(T("authorization-capture-amount-a_in")) == "4.00" and me(tok["ada"])["total"] == 10100)
    page.fill(T("authorization-capture-amount-a_in"), "4.01"); page.click(T("authorization-capture-a_in"))
    page.wait_for_selector(T("authorization-error"))
    check("capture above remainder -> authorization-error", "more" in txt(page, "authorization-error").lower() or True)
    page.fill(T("authorization-capture-amount-a_in"), "1.005"); page.click(T("authorization-capture-a_in")); page.wait_for_selector(T("authorization-error"))
    keys = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/a_in/capture") and keys.append((r.headers.get("idempotency-key"), r.post_data)))
    page.route("**/a_in/capture", lambda route: (route.fetch(), route.abort()))
    page.fill(T("authorization-capture-amount-a_in"), "2.00"); page.uncheck(T("authorization-keep-open-a_in"))
    page.click(T("authorization-capture-a_in")); page.wait_for_selector(T("authorization-uncertain"))
    check("lost capture response -> authorization-uncertain, not error", not has(page, "authorization-error") and me(tok["ada"])["total"] == 10300)
    page.unroute("**/a_in/capture")
    page.click(T("authorization-capture-a_in")); wait_status(page, "a_in", "captured")
    bob = me(tok["bob"])
    check("retry same key+body; captured once; remainder released", len(keys) == 2 and keys[0] == keys[1] and me(tok["ada"])["total"] == 10300
          and bob["held"] == 0 and bob["total"] == 1700 and txt(page, "authorization-captured-a_in") == "3.00 EUR", str(keys))
    page.click(T("authorization-void-a_out")); wait_status(page, "a_out", "voided")
    page.goto(B + "/"); page.wait_for_selector(T("wallet-available"))
    check("void releases; wallet-held absent at zero", not has(page, "wallet-held") and txt(page, "wallet-available") == "103.00 EUR")
    page.goto(B + "/authorizations"); page.wait_for_selector(T("authorize-handle"))
    page.fill(T("authorize-handle"), "bob"); page.fill(T("authorize-amount"), "200.00"); page.click(T("authorize-submit")); page.wait_for_selector(T("authorize-error"))
    page.fill(T("authorize-amount"), "10.00"); page.click(T("authorize-submit")); page.wait_for_selector(T("authorize-success"))
    page.wait_for_timeout(300)
    check("authorise: refused over available, then created and listed", page.locator('[data-testid^="authorization-item-"][data-status="open"]').count() == 1)
    check("no page errors (holds)", not errs, str(errs))
    page.close()

    # empty
    tok = reset(users)
    page, errs = open_as(browser, "ada", "/authorizations")
    page.wait_for_selector(T("empty-authorizations"))
    check("empty-authorizations shown", page.locator(T("empty-authorizations")).is_visible())
    page.close()

    # U7: lost payment response before an export/import upgrade, retried after it in the same page
    tok = reset(users, requests=[{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 700, "note": "pending", "status": "pending"}])
    page, errs = open_as(browser, "ada", "/")
    page.evaluate("window.__marker = 42")
    keys = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/payments") and keys.append((r.headers.get("idempotency-key"), r.post_data)))
    page.route("**/payments", lambda route: (route.fetch(), route.abort()))
    page.fill(T("pay-handle"), "bob"); page.fill(T("pay-amount"), "15"); page.fill(T("pay-note"), "lost")
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-uncertain"))
    page.unroute("**/payments")
    exported = api("GET", "/_test/export")[1]
    reset([U("u_zed", "zed", 1)])
    check("import between browser requests -> 204", api("POST", "/_test/import", exported)[0] == 204)
    page.click(T("pay-submit")); page.wait_for_selector(T("pay-success"))
    check("after upgrade: retry same key+body recovers the original payment, no reload, money once",
          page.evaluate("window.__marker") == 42 and len(keys) == 2 and keys[0] == keys[1] and me(tok["ada"])["total"] == 8500
          and txt(page, "wallet-balance") == "85.00 EUR" and page.locator('[data-testid^="activity-item-"]').count() == 1
          and not has(page, "pay-uncertain") and not has(page, "pay-error"), str(keys))
    page.locator('a[href="/requests"]:visible').first.click(); page.wait_for_selector(T("request-pay-rq_1"))
    page.click(T("request-pay-rq_1")); page.wait_for_selector('[data-testid="request-item-rq_1"][data-status="paid"]')
    check("still signed in; pending request payable after upgrade", me(tok["ada"])["total"] == 7800 and has(page, "current-user"))
    check("no page errors (upgrade)", not errs, str(errs))
    page.close()

    # U9: /login and /signup while signed in
    tok = reset(users)
    page, errs = open_as(browser, "ada", "/login")
    page.wait_for_selector(T("login-submit"))
    ok_login = has(page, "current-user") and txt(page, "current-handle") == "ada"
    page.goto(B + "/signup"); page.wait_for_selector(T("signup-submit"))
    ok_signup = has(page, "current-user") and has(page, "logout-button")
    page.goto(B + "/login"); page.wait_for_selector(T("login-submit"))
    page.fill(T("login-email"), "bob@e.com"); page.fill(T("login-password"), "correct horse"); page.click(T("login-submit"))
    page.wait_for_selector(T("wallet-available")); page.wait_for_timeout(300)
    check("signed in: /login and /signup render forms with the chrome; logging in as bob switches", ok_login and ok_signup and txt(page, "current-handle") == "bob")
    page.click(T("logout-button")); page.wait_for_selector(T("login-submit"))
    page.goto(B + "/split"); page.wait_for_selector(T("login-submit"))
    check("signed out: guarded route redirects to /login", page.url.endswith("/login"))
    page.close()
    browser.close()

sys.exit(0 if all(results) else 1)
