"""Tiny fake UI for checking walker.py itself: one clean page and one with planted defects.

    python3 reviews/stage2/tools/selftest/server.py 18431
"""
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STYLE = """<style>body{font:16px system-ui;margin:24px;color:#1a1a1a;background:#fff}
input,button{font:inherit;padding:8px}button:focus-visible,input:focus-visible{outline:3px solid #2457d6}</style>"""

LOGIN = STYLE + """<h1>Sign in</h1>
<label for=e>Email</label><input id=e data-testid=login-email>
<label for=p>Password</label><input id=p type=password data-testid=login-password>
<button data-testid=login-submit onclick="location='/'">Sign in</button>"""

GOOD = STYLE + """<header><span data-testid=current-user>Ada</span></header>
<p data-testid=wallet-balance data-amount=10000>100.00 EUR</p>
<label for=h>Recipient</label><input id=h data-testid=pay-handle>
<button data-testid=pay-submit onclick="document.body.insertAdjacentHTML('beforeend',
 '<p data-testid=pay-error>Refused</p>')">Pay</button>"""

BAD = """<style>body{margin:0}*:focus{outline:none}</style>
<span data-testid=current-user>Ada</span>
<div style="width:2000px;color:#bbb;background:#fff">wide and faint</div>
<input data-testid=pay-handle><button>Pay</button>
<script>console.error('planted error')</script>"""

PAGES = {"/login": LOGIN, "/": GOOD, "/bad": BAD}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((body or "not found").encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
