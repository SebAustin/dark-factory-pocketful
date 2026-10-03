"""Entry point: python -m app.server. Listens on 0.0.0.0:$PORT (default 8080)."""
import importlib
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import errors, routes
from .http_util import CONTENT_TYPE, Ctx, encode

# Route modules register themselves on import. Modules not built yet are skipped.
ROUTE_MODULES = ("testctl", "auth", "payments", "requests_", "splits", "settlements",
                 "transfer_io")
MAX_BODY = 1024 * 1024


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
            status, body = 500, {"error": {"code": "internal_error",
                                           "message": "internal error"}}
        self._send(status, body)

    def _dispatch(self):
        length = self.headers.get("Content-Length")
        try:
            n = int(length) if length else 0
        except ValueError:
            raise errors.malformed("invalid Content-Length")
        if n < 0 or n > MAX_BODY:
            raise errors.malformed("invalid Content-Length")
        raw = self.rfile.read(n) if n else b""
        return routes.dispatch(Ctx(self.command, self.path, self.headers, raw))

    def _send(self, status, body):
        data = b"" if status == 204 or body is None else encode(body)
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    def log_message(self, fmt, *args):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 1024
    allow_reuse_address = True


def make_server(host: str, port: int) -> Server:
    _load_route_modules()
    return Server((host, port), Handler)


def main():
    port = int(os.environ.get("PORT") or 8080)
    srv = make_server("0.0.0.0", port)
    print("pocketful listening on 0.0.0.0:{}".format(port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
