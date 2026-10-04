"""S2.1: HTML pages, Accept negotiation on shared routes, static assets (stage 2 routes table)."""
import os
import shutil
import tempfile
import unittest

from harness import call, reset
from test_payments import token

from app import web

HTML = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


class WebRootCase(unittest.TestCase):
    """Points the seam at a throwaway web root so tests never touch the designer's web/."""

    files = {}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        for rel, text in self.files.items():
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.saved = web.WEB_ROOT
        web.WEB_ROOT = self.root

    def tearDown(self):
        web.WEB_ROOT = self.saved
        shutil.rmtree(self.root)


class PageTest(WebRootCase):
    files = {"index.html": "<!doctype html><title>shell</title>",
             "login.html": "<!doctype html><title>login page</title>",
             "assets/app.js": "console.log(1)",
             "assets/css/site.css": "body{}",
             "assets/logo.svg": "<svg/>"}

    def test_always_html_routes(self):
        for path in ("/", "/split", "/signup"):
            r = call("GET", path)
            self.assertEqual(r.status, 200, path)
            self.assertTrue(r.headers["Content-Type"].startswith("text/html; charset=utf-8"))
            self.assertIn("shell", r.raw)
            self.assertEqual(r.headers["Cache-Control"], "no-cache")
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("login page", call("GET", "/login").raw)
        self.assertIn("login page", call("GET", "/login?next=%2F").raw)

    def test_shared_routes_negotiate(self):
        reset()
        tok = token("ada@example.com")
        for path in ("/requests", "/authorizations"):
            r = call("GET", path, headers=HTML)
            self.assertEqual(r.status, 200, path)
            self.assertTrue(r.headers["Content-Type"].startswith("text/html"))
        r = call("GET", "/requests", token=tok)
        self.assertEqual(r.status, 200)
        self.assertIn("requests", r.body)
        r = call("GET", "/requests", token=tok, headers={"Accept": "*/*"})
        self.assertIn("requests", r.body)
        r = call("GET", "/requests", token=tok, headers={"Accept": "application/json"})
        self.assertIn("requests", r.body)
        r = call("GET", "/requests", headers={"Accept": "application/json"})
        self.assertEqual((r.status, r.code), (401, "unauthenticated"))
        r = call("GET", "/requests", headers={"Accept": "text/html;q=0, application/json"})
        self.assertEqual(r.status, 401)
        r = call("POST", "/requests", {"payer_handle": "bob", "amount": 1}, token=tok,
                 key="k-web", headers=HTML)
        self.assertEqual(r.status, 201)
        self.assertEqual(r.body["status"], "pending")

    def test_shared_urls_vary_on_accept(self):
        reset()
        tok = token("ada@example.com")
        for path in ("/requests", "/authorizations"):
            self.assertEqual(call("GET", path, headers=HTML).headers.get("Vary"), "Accept")
            self.assertEqual(call("GET", path).headers.get("Vary"), "Accept")  # 401/404 JSON
        self.assertEqual(call("GET", "/requests", token=tok).headers.get("Vary"), "Accept")
        self.assertIsNone(call("GET", "/activity", token=tok).headers.get("Vary"))

    def test_assets(self):
        r = call("GET", "/assets/app.js")
        self.assertEqual((r.status, r.raw), (200, "console.log(1)"))
        self.assertTrue(r.headers["Content-Type"].startswith("text/javascript"))
        self.assertTrue(call("GET", "/assets/css/site.css").headers["Content-Type"]
                        .startswith("text/css"))
        self.assertEqual(call("GET", "/assets/logo.svg").headers["Content-Type"],
                         "image/svg+xml")
        etag = r.headers["ETag"]
        again = call("GET", "/assets/app.js", headers={"If-None-Match": etag})
        self.assertEqual(again.status, 304)
        self.assertEqual(again.raw, "")

    def test_asset_traversal_and_missing_are_404_envelope(self):
        for path in ("/assets/../app/store.py", "/assets/%2e%2e/app/store.py",
                     "/assets/..%2fapp%2fstore.py", "/assets/a%00b", "/assets/",
                     "/assets/nope.js", "/assets//etc/passwd", "/assets/%2Fetc%2Fpasswd",
                     "/assets/css"):
            r = call("GET", path)
            self.assertEqual((r.status, r.code), (404, "not_found"), path)

    def test_head_and_wrong_method(self):
        r = call("HEAD", "/")
        self.assertEqual((r.status, r.raw), (200, ""))
        self.assertEqual(call("POST", "/").status, 405)
        self.assertEqual(call("POST", "/split").code, "method_not_allowed")

    def test_file_changes_are_picked_up(self):
        with open(os.path.join(self.root, "index.html"), "w") as fh:
            fh.write("<!doctype html><title>new shell, longer</title>")
        self.assertIn("new shell", call("GET", "/").raw)


class AppShellTest(WebRootCase):
    files = {"app.html": "<!doctype html><title>app shell</title>"}

    def test_app_html_is_a_shell_too(self):
        for path in ("/", "/split", "/login"):
            self.assertIn("app shell", call("GET", path).raw)
        self.assertIn("app shell", call("GET", "/authorizations", headers=HTML).raw)


class PlaceholderTest(WebRootCase):
    files = {}

    def test_placeholder_without_designer_files(self):
        r = call("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("Pocketful", r.raw)
        self.assertEqual(call("GET", "/assets/app.js").status, 404)


if __name__ == "__main__":
    unittest.main()


class NoNetworkStartupTest(unittest.TestCase):
    def test_bind_does_no_dns_lookup(self):
        import socket
        from app import server
        saved = socket.getfqdn

        def boom(*args):
            raise AssertionError("DNS lookup at startup")
        socket.getfqdn = boom
        try:
            srv = server.make_server("127.0.0.1", 0)
            srv.server_close()
        finally:
            socket.getfqdn = saved
