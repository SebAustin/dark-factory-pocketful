"""The HTML/static seam (stage 2 routes table; plan §6).

Serves the designer's files from stage-2/web/ (WEB_ROOT): page routes return web/<name>.html or
the web/index.html shell; /assets/<path> returns files under web/assets/. The API stays JSON;
/requests and /authorizations answer HTML only when the Accept header asks for it (routes.py).
Nothing here touches service state, so no route takes the lock.
"""
import hashlib
import os
from urllib.parse import unquote

from . import errors
from .http_util import Raw
from .routes import HTML_ALTERNATES, route

WEB_ROOT = os.environ.get("POCKETFUL_WEB_ROOT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

PAGES = {"/": "index.html", "/split": "split.html", "/signup": "signup.html",
         "/login": "login.html", "/requests": "requests.html",
         "/authorizations": "authorizations.html"}
SHARED_WITH_API = ("/requests", "/authorizations")
SHELLS = ("index.html", "app.html")  # single-page shell, either name

TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
    ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8", ".map": "application/json; charset=utf-8",
}
HTML_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                               "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
                               "base-uri 'self'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}
PLACEHOLDER = (b"<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
               b"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
               b"<title>Pocketful</title><main><h1>Pocketful</h1>"
               b"<p>The wallet screens are on their way.</p></main></html>")

_cache: dict = {}  # absolute path -> (mtime_ns, size, data, etag)


def _read(path: str):
    """File bytes and ETag, cached until the file changes. None if it is not a regular file."""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    if not os.path.isfile(path):
        return None
    hit = _cache.get(path)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2], hit[3]
    with open(path, "rb") as fh:
        data = fh.read()
    etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
    _cache[path] = (st.st_mtime_ns, st.st_size, data, etag)
    return data, etag


def _inside(root: str, rel: str):
    """Absolute path of rel under root, or None if it would escape root."""
    if "\x00" in rel or rel.startswith(("/", "\\")):
        return None
    root = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root, rel))
    return full if full.startswith(root + os.sep) else None


def _file_response(ctx, data: bytes, etag: str, content_type: str, extra: dict):
    """(status, Raw) for the pipeline; 304 when the client already holds this version."""
    headers = {"Content-Type": content_type, "ETag": etag, **extra}
    if etag in [t.strip() for t in (ctx.header("If-None-Match") or "").split(",")]:
        return 304, Raw(304, b"", headers)
    return 200, Raw(200, data, headers)


def page(ctx, state, user):
    name = PAGES[ctx.path]
    for candidate in (name, *SHELLS):
        path = _inside(WEB_ROOT, candidate)
        found = _read(path) if path else None
        if found:
            return _file_response(ctx, found[0], found[1], TYPES[".html"], HTML_HEADERS)
    return 200, Raw(200, PLACEHOLDER, {"Content-Type": TYPES[".html"], **HTML_HEADERS})


for _path in PAGES:
    if _path in SHARED_WITH_API:
        HTML_ALTERNATES[_path] = page
    else:
        route("GET", _path, auth=False, locked=False)(page)


@route("GET", "/assets/{path*}", auth=False, locked=False)
def asset(ctx, state, user):
    rel = unquote(ctx.params["path"])
    path = _inside(os.path.join(WEB_ROOT, "assets"), rel)
    found = _read(path) if path else None
    if not found:
        raise errors.not_found("no such asset")
    content_type = TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    return _file_response(ctx, found[0], found[1], content_type,
                          {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
