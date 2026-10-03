"""Verifier behavioural scenarios for `/requests` (U4) and `/split` (U5).

    $PY reviews/stage2/tools/scenarios_requests_split.py http://127.0.0.1:<port> [width]
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


U = lambda i, h, b: {"id": i, "email": h + "@e.com", "password": "correct horse", "display_name": h.title(),
                     "handle": h, "balance": b}


def reset(ada=10000, requests=()):
    assert api("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                                         "users": [U("u_ada", "ada", ada), U("u_bob", "bob", 5000), U("u_cy", "cy", 0)],
                                         "requests": list(requests)})[0] == 204
    return {h: api("POST", "/auth/login", {"email": h + "@e.com", "password": "correct horse"})[1]["token"]
            for h in ("ada", "bob", "cy")}


R = lambda i, rq, py, amt, st="pending": {"id": i, "requester_id": rq, "payer_id": py, "amount": amt, "note": "n " + i, "status": st}
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail))


def page_as(browser, route, who="ada"):
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


def status(page, rid):
    return page.get_attribute(T("request-item-" + rid), "data-status")


def has(page, tid):
    return page.locator(T(tid)).count() > 0


def total(tok):
    return api("GET", "/me", tok=tok)[1]["total"]


with sync_playwright() as p:
    browser = p.chromium.launch()

    # requests: presence rules and amounts
    tok = reset(requests=[R("rq_in", "u_bob", "u_ada", 1200), R("rq_out", "u_ada", "u_cy", 99999),
                          R("rq_dec", "u_bob", "u_ada", 300, "declined"), R("rq_stale", "u_bob", "u_ada", 700)])
    page, errs = page_as(browser, "/requests")
    check("presence rules", has(page, "request-pay-rq_in") and has(page, "request-decline-rq_in") and not has(page, "request-cancel-rq_in")
          and has(page, "request-cancel-rq_out") and not has(page, "request-pay-rq_out")
          and not has(page, "request-pay-rq_dec") and not has(page, "request-decline-rq_dec") and status(page, "rq_dec") == "declined"
          and page.inner_text(T("request-amount-rq_out")).strip() == "999.99 EUR" and not page.locator(T("empty-requests")).is_visible()
          and has(page, "incoming-list") and has(page, "outgoing-list") and not has(page, "request-error"))
    # cancelled elsewhere while the pay button is visible
    api("POST", "/requests/rq_stale/cancel", None, tok["bob"])
    page.click(T("request-pay-rq_stale"))
    page.wait_for_selector(T("request-error"))
    page.wait_for_timeout(500)
    check("stale pay -> request-error, list refreshed, pay button gone", status(page, "rq_stale") == "cancelled"
          and not has(page, "request-pay-rq_stale") and total(tok["ada"]) == 10000)
    # pay moves money once and refreshes
    page.click(T("request-pay-rq_in"))
    page.wait_for_selector('[data-testid="request-item-rq_in"][data-status="paid"]')
    check("pay -> paid, money moved once, no buttons, error cleared",
          total(tok["ada"]) == 8800 and not has(page, "request-pay-rq_in") and not has(page, "request-error"))
    page.click(T("request-cancel-rq_out"))
    page.wait_for_selector('[data-testid="request-item-rq_out"][data-status="cancelled"]')
    check("cancel outgoing -> cancelled, button gone", not has(page, "request-cancel-rq_out"))
    check("no page errors (requests)", not errs, str(errs))
    page.close()

    # insufficient funds, decline, lost response on a request pay
    tok = reset(ada=100, requests=[R("rq_big", "u_bob", "u_ada", 5000), R("rq_d", "u_bob", "u_ada", 1), R("rq_l", "u_bob", "u_ada", 50)])
    page, errs = page_as(browser, "/requests")
    page.click(T("request-pay-rq_big")); page.wait_for_selector(T("request-error"))
    check("insufficient funds -> request-error, still pending", status(page, "rq_big") == "pending" and has(page, "request-pay-rq_big"))
    page.click(T("request-decline-rq_d"))
    page.wait_for_selector('[data-testid="request-item-rq_d"][data-status="declined"]')
    check("decline -> declined, buttons gone", not has(page, "request-pay-rq_d") and not has(page, "request-decline-rq_d"))
    keys = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/rq_l/pay") and keys.append(r.headers.get("idempotency-key")))
    page.route("**/rq_l/pay", lambda route: (route.fetch(), route.abort()))
    page.click(T("request-pay-rq_l")); page.wait_for_selector(T("request-uncertain"))
    check("lost pay response -> request-uncertain, not request-error", not has(page, "request-error") and total(tok["ada"]) == 50)
    page.unroute("**/rq_l/pay")
    page.click(T("request-pay-rq_l"))
    page.wait_for_selector('[data-testid="request-item-rq_l"][data-status="paid"]')
    check("retry same key, paid once", len(keys) == 2 and keys[0] == keys[1] and total(tok["ada"]) == 50, str(keys))
    page.close()

    # empty
    reset()
    page, errs = page_as(browser, "/requests")
    check("empty-requests shown when both lists are empty", page.locator(T("empty-requests")).is_visible())
    page.close()

    # split: preview equals the server's shares (§9 rows) and posts nothing until submit
    tok = reset()
    page, errs = page_as(browser, "/split")
    posts = []
    page.on("request", lambda r: r.method == "POST" and r.url.endswith("/splits") and posts.append(r.post_data))
    rows = [("10.00", "ada,bob,cy", [334, 333, 333]), ("0.01", "ada,bob,cy", [1, 0, 0]), ("0.10", "cy,bob,ada", [4, 3, 3]),
            ("9.99", "ada,bob,cy", [333, 333, 333])]
    fmt = lambda m: "%d.%02d EUR" % divmod(m, 100)
    okrows = []
    for amt, hs, want in rows:
        page.fill(T("split-amount"), amt); page.fill(T("split-handles"), hs)
        got = [page.inner_text(T("split-share-" + x)).strip() for x in hs.split(",")]
        okrows.append(got == [fmt(w) for w in want])
    check("§9 rows in the preview, nothing posted", all(okrows) and not posts, str(okrows))
    page.fill(T("split-amount"), "10.00"); page.fill(T("split-handles"), "bob,cy"); page.fill(T("split-note"), "dinner")
    preview = {x: page.inner_text(T("split-share-" + x)).strip() for x in ("bob", "cy")}
    page.click(T("split-submit")); page.wait_for_selector(T("split-success"))
    reqs = api("GET", "/requests?direction=outgoing", tok=tok["ada"])[1]["requests"]
    server = {r["payer_handle"]: fmt(r["amount"]) for r in reqs}
    check("submitted split = preview (caller omitted, n = 2)", server == preview and len(posts) == 1, "%s vs %s" % (server, preview))
    page.click(T("split-submit")); page.wait_for_timeout(500)
    check("unchanged resubmit posts nothing", len(posts) == 1 and has(page, "split-already"))
    page.fill(T("split-handles"), "bob,nobody"); page.click(T("split-submit")); page.wait_for_selector(T("split-error"))
    check("unknown handle -> split-error", True)
    page.fill(T("split-amount"), "1.005"); page.fill(T("split-handles"), "bob"); n = len(posts)
    page.click(T("split-submit")); page.wait_for_selector(T("split-error"))
    check("1.005 -> split-error, no request", len(posts) == n)
    page.fill(T("split-amount"), "10"); page.fill(T("split-handles"), "ada"); page.click(T("split-submit")); page.wait_for_selector(T("split-success"))
    check("caller only -> success, one share 10.00 EUR", page.inner_text(T("split-share-ada")).strip() == "10.00 EUR")
    check("no page errors (split)", not errs, str(errs))
    page.close()
    browser.close()

sys.exit(0 if all(results) else 1)
