"""Entry point: python -m app.server. Listens on 0.0.0.0:$PORT (default 8080)."""
import importlib
import os
import sys
import threading
import traceback
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import errors, routes
from .http_util import CONTENT_TYPE, Ctx, encode

# Route modules register themselves on import. Modules not built yet are skipped.
ROUTE_MODULES = ("testctl", "auth", "payments", "requests_", "splits", "settlements",
                 "transfer_io")
MAX_BODY = 1024 * 1024                 # ordinary API bodies
MAX_STATE_BODY = 64 * 1024 * 1024      # reset fixtures and import snapshots
STATE_PATHS = ("/_test/reset", "/_test/import")
DRAIN_CHUNK = 64 * 1024
# musl (python:3.12-alpine) gives threads a tiny C stack; C-level recursion (json, re) needs room.
THREAD_STACK = 16 * 1024 * 1024
INTERNAL_ERROR = {"error": {"code": "internal_error", "message": "internal error"}}


def _load_route_modules():
    for name in ROUTE_MODULES:
        try:
            importlib.import_module("app." + name)
        except ModuleNotFoundError as exc:
            if exc.name != "app." + name:
                raise


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pocketful"
    sys_version = ""

    def _handle(self):
        try:
            status, body = self._dispatch()
        except errors.ApiError as err:
            status, body = err.status, err.envelope()
        except Exception:  # never drop a connection or leak a traceback to the client
            traceback.print_exc(file=sys.stderr)
            status, body = 500, INTERNAL_ERROR
        try:
            self._send(status, body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.close_connection = True

    def _dispatch(self):
        length = self.headers.get("Content-Length")
        try:
            n = int(length) if length else 0
        except ValueError:
            raise errors.malformed("invalid Content-Length")
        if n < 0:
            raise errors.malformed("invalid Content-Length")
        cap = MAX_STATE_BODY if urlsplit(self.path).path in STATE_PATHS else MAX_BODY
        if n > cap:
            self._discard(n)
            raise errors.malformed("request body too large")
        raw = self.rfile.read(n) if n else b""
        method = "GET" if self.command == "HEAD" else self.command
        return routes.dispatch(Ctx(method, self.path, self.headers, raw))

    def _discard(self, n):
        """Read and drop an oversized body so the client receives the 400, not a reset."""
        if n > MAX_STATE_BODY:
            self.close_connection = True
            return
        while n > 0:
            chunk = self.rfile.read(min(n, DRAIN_CHUNK))
            if not chunk:
                break
            n -= len(chunk)

    def _send(self, status, body):
        data = b"" if status == 204 or body is None else encode(body)
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def __getattr__(self, name):
        # Every method reaches the router, which answers 404 or 405 with the envelope.
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def send_error(self, code, message=None, explain=None):
        """Replace the stdlib HTML error page: protocol-level failures get the envelope too."""
        if code in (405, 501):
            status, err = 405, "method_not_allowed"
        elif code == 404:
            status, err = 404, "not_found"
        elif 400 <= code < 500:
            status, err = code, "malformed_request"
        else:
            status, err = 400, "malformed_request"
        if self.request_version == "HTTP/0.9" or not self.request_version.startswith("HTTP/1."):
            self.request_version = "HTTP/1.1"  # always emit a status line and headers
        data = encode({"error": {"code": err, "message": message or "malformed request"}})
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 1024
    allow_reuse_address = True


def make_server(host: str, port: int) -> Server:
    threading.stack_size(THREAD_STACK)  # applies to every request thread created later
    _load_route_modules()
    return Server((host, port), Handler)


def main():
    port = int(os.environ.get("PORT") or 8080)
    srv = make_server("0.0.0.0", port)
    print("pocketful listening on 0.0.0.0:{}".format(port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
