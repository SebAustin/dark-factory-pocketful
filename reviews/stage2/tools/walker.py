#!/usr/bin/env python3
"""Verifier browser walk for stage 2 screens (Playwright, Chromium).

    PY=/Users/sebastienhenry/dark-factory/dark-factory-wearedevs/.venv/bin/python
    $PY reviews/stage2/tools/walker.py --base http://127.0.0.1:18430 \
        --plan reviews/stage2/tools/plan.stage2.json --out reviews/stage2/shots/<item>-<rev>

For each viewport (default 375, 390, 1280 CSS px) and each state in the plan: optionally reset the
service with a fixture, sign in, open the route, run the state's steps, then record
  - a full-page screenshot   <out>/<viewport>/<NN>-<state>.png
  - horizontal overflow      document.scrollingElement.scrollWidth <= innerWidth
  - console errors, page errors and 5xx responses seen while in that state
  - unlabelled form controls (no <label for>, wrapping label, aria-label or aria-labelledby)
  - focus visibility         Tab through the page; each focused control must change its outline,
                             box-shadow, border or background versus its unfocused style
  - text contrast            WCAG ratio of visible text against its first opaque ancestor background
                             (< 4.5, or < 3 for large text, is reported)
  - expected test ids        every `expect` id must be present (and visible unless listed in `hidden_ok`)
and writes <out>/report.json plus <out>/report.md. Exit status 1 if any check failed.

Plan format (JSON):
{
  "fixture": {...stage-1 reset fixture...} | null,          # applied before each state when set
  "login": {"email": "...", "password": "..."} | null,      # UI login via login-email/-password/-submit
  "states": [
    {"name": "wallet-empty", "route": "/", "expect": ["wallet-balance", "empty-activity"],
     "steps": [{"fill": "pay-handle", "value": "bob"}, {"click": "pay-submit"},
               {"wait": "pay-error"}, {"press": "Tab"}, {"route": {"url": "**/payments",
                "abort": true}}],
     "fixture": {...} | null, "login": false, "hidden_ok": [],
     "allow_console": ["status of 4\\d\\d"]}     # regexes for expected console lines (refusal states)
  ]
}
Steps address elements by data-testid. "route" steps intercept network calls (abort or delay ms) so
loading, refused and uncertain states can be staged deterministically.
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = (375, 390, 1280)
HEIGHT = 900
STEP_TIMEOUT_MS = 8000
FOCUS_TABS = 25

OVERFLOW_JS = """() => {
  const el = document.scrollingElement || document.documentElement;
  return {scrollWidth: el.scrollWidth, innerWidth: window.innerWidth};
}"""

UNLABELLED_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (el.type === 'hidden' || el.offsetParent === null) continue;
    const id = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    const named = id || el.closest('label') || el.getAttribute('aria-label')
      || el.getAttribute('aria-labelledby');
    if (!named) out.push(el.getAttribute('data-testid') || el.name || el.outerHTML.slice(0, 80));
  }
  return out;
}"""

FOCUS_STYLE_JS = """(el) => {
  const s = getComputedStyle(el);
  return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderColor,
          s.backgroundColor, s.textDecorationLine].join('|');
}"""

CONTRAST_JS = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(',').map(Number); return {r:p[0], g:p[1], b:p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = ({r,g,b}) => { const f = v => { v /= 255; return v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4; };
    return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b); };
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor);
    if (c && c.a >= 0.99) return c; } return {r:255, g:255, b:255, a:1}; };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const el = walker.currentNode.parentElement;
    if (!el || seen.has(el) || !walker.currentNode.textContent.trim()) continue;
    seen.add(el);
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    if (s.visibility === 'hidden' || s.display === 'none' || r.width === 0 || r.height === 0) continue;
    const fg = parse(s.color); if (!fg) continue;
    const a = lum(fg), b = lum(bg(el)), ratio = (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
    const size = parseFloat(s.fontSize), large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) out.push({text: walker.currentNode.textContent.trim().slice(0, 40),
      ratio: Math.round(ratio*100)/100, testid: el.closest('[data-testid]')?.getAttribute('data-testid') || null});
  }
  return out;
}"""


def tid(testid):
    return f'[data-testid="{testid}"]'


def reset(base, fixture):
    req = urllib.request.Request(base + "/_test/reset", data=json.dumps(fixture).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 204:
            raise RuntimeError("reset returned %d" % resp.status)


def ui_login(page, base, login):
    page.goto(base + "/login")
    page.fill(tid("login-email"), login["email"])
    page.fill(tid("login-password"), login["password"])
    page.click(tid("login-submit"))
    page.wait_for_selector(tid("current-user"), timeout=STEP_TIMEOUT_MS)


def run_step(page, step):
    if "fill" in step:
        page.fill(tid(step["fill"]), str(step["value"]))
    elif "select" in step:
        page.select_option(tid(step["select"]), step["value"])
    elif "click" in step:
        page.click(tid(step["click"]))
    elif "wait" in step:
        page.wait_for_selector(tid(step["wait"]), timeout=STEP_TIMEOUT_MS)
    elif "gone" in step:
        page.wait_for_selector(tid(step["gone"]), state="detached", timeout=STEP_TIMEOUT_MS)
    elif "press" in step:
        page.keyboard.press(step["press"])
    elif "route" in step:
        spec = step["route"]
        if spec.get("abort"):
            page.route(spec["url"], lambda route: route.abort())
        elif spec.get("hold"):  # never answered while the walk lasts: a frozen in-flight state
            page.route(spec["url"], lambda route: None)
        else:
            delay_s = spec.get("delay_ms", 0) / 1000
            page.route(spec["url"], lambda route: (time.sleep(delay_s), route.continue_()))
    elif "unroute" in step:
        page.unroute(step["unroute"])
    else:
        raise ValueError("unknown step " + json.dumps(step))


def focus_problems(page):
    """Tab through the page; report focused controls whose style does not change on focus."""
    problems, seen = [], set()
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    for _ in range(FOCUS_TABS):
        page.keyboard.press("Tab")
        handle = page.evaluate_handle("() => document.activeElement")
        key = page.evaluate("(el) => el === document.body ? null : (el.getAttribute('data-testid') "
                            "|| el.tagName + ':' + (el.textContent || el.name || '').trim().slice(0,30))",
                            handle)
        if key is None or key in seen:
            continue
        seen.add(key)
        focused = page.evaluate(FOCUS_STYLE_JS, handle)
        page.evaluate("(el) => el.blur()", handle)
        unfocused = page.evaluate(FOCUS_STYLE_JS, handle)
        page.evaluate("(el) => el.focus()", handle)
        if focused == unfocused:
            problems.append(key)
    return problems


def check_state(page, state):
    missing = []
    for testid in state.get("expect", []):
        loc = page.locator(tid(testid))
        if loc.count() == 0 or (testid not in state.get("hidden_ok", []) and not loc.first.is_visible()):
            missing.append(testid)
    overflow = page.evaluate(OVERFLOW_JS)
    return {
        "missing_testids": missing,
        "overflow": overflow if overflow["scrollWidth"] > overflow["innerWidth"] else None,
        "unlabelled": page.evaluate(UNLABELLED_JS),
        "low_contrast": page.evaluate(CONTRAST_JS),
        "focus_not_visible": focus_problems(page),
    }


def walk_state(browser, base, plan, state, width, shot):
    context = browser.new_context(viewport={"width": width, "height": HEIGHT})
    page = context.new_page()
    events = []
    page.on("console", lambda m: m.type == "error" and events.append("console: " + m.text))
    page.on("pageerror", lambda e: events.append("pageerror: " + str(e)))
    page.on("response", lambda r: r.status >= 500 and events.append("5xx: %d %s" % (r.status, r.url)))
    result = {"state": state["name"], "viewport": width, "screenshot": str(shot)}
    try:
        fixture = state.get("fixture", plan.get("fixture"))
        if fixture:
            reset(base, fixture)
        login = plan.get("login")
        if login and state.get("login", True):
            ui_login(page, base, login)
        page.goto(base + state["route"])
        page.wait_for_load_state("networkidle")
        for step in state.get("steps", []):
            run_step(page, step)
        page.screenshot(path=str(shot), full_page=True)
        result.update(check_state(page, state))
    except Exception as exc:  # a failed walk is a finding, not a crash of the walker
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:
            pass
    allowed = [re.compile(p) for p in state.get("allow_console", [])]
    result["events"] = [e for e in events if not any(p.search(e) for p in allowed)]
    result["allowed_events"] = [e for e in events if any(p.search(e) for p in allowed)]
    context.close()
    return result


def failed(r):
    return bool(r.get("error") or r.get("missing_testids") or r.get("overflow") or r.get("unlabelled")
                or r.get("low_contrast") or r.get("focus_not_visible") or r.get("events"))


def write_reports(out, results):
    (out / "report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    lines = ["| viewport | state | result | details |", "|---|---|---|---|"]
    for r in results:
        details = {k: r[k] for k in ("error", "missing_testids", "overflow", "unlabelled",
                                     "low_contrast", "focus_not_visible", "events") if r.get(k)}
        lines.append("| %s | %s | %s | %s |" % (r["viewport"], r["state"],
                                                 "FAIL" if failed(r) else "ok",
                                                 json.dumps(details, ensure_ascii=False)[:400]))
    (out / "report.md").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--viewports", default=",".join(map(str, VIEWPORTS)))
    args = ap.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    out = Path(args.out)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in map(int, args.viewports.split(",")):
            (out / str(width)).mkdir(parents=True, exist_ok=True)
            for i, state in enumerate(plan["states"], 1):
                shot = out / str(width) / ("%02d-%s.png" % (i, state["name"]))
                results.append(walk_state(browser, args.base.rstrip("/"), plan, state, width, shot))
        browser.close()
    write_reports(out, results)
    bad = [r for r in results if failed(r)]
    print("%d state walks, %d with findings; report: %s" % (len(results), len(bad), out / "report.md"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
