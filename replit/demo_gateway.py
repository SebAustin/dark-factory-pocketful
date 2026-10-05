"""Public gateway for the Replit demo of stage 4 (deployment glue, not part of the band's output).

Forwards every request to the band's service on an internal port, except the test-control
endpoints (`/_test/...`), which the event's specification exposes for the judges' harness.
On a public URL those would let anyone wipe or replace the demo data, so here they answer 404.
Python standard library only.
"""
import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUBLIC_PORT = int(os.environ.get("PORT") or 8080)
APP_PORT = int(os.environ.get("APP_PORT") or 18080)
BLOCKED_PREFIX = "/_test/"
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
              "proxy-authorization", "proxy-authenticate", "host"}


class Gateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        if self.path.startswith(BLOCKED_PREFIX):
            self._reply(404, b'{"error":{"code":"not_found","message":"Not available on the public demo."}}')
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        upstream = http.client.HTTPConnection("127.0.0.1", APP_PORT, timeout=30)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            resp = upstream.getresponse()
            data = resp.read()
        except OSError:
            self._reply(502, b'{"error":{"code":"unavailable","message":"The demo service is starting."}}')
            return
        finally:
            upstream.close()
        self.send_response(resp.status, resp.reason)
        for key, value in resp.getheaders():
            if key.lower() not in HOP_BY_HOP and key.lower() != "content-length":
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _reply(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _forward

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"demo gateway on 0.0.0.0:{PUBLIC_PORT} -> 127.0.0.1:{APP_PORT} ({BLOCKED_PREFIX}* blocked)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PUBLIC_PORT), Gateway).serve_forever()
