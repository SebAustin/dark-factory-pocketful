"""Routing table and the request pipeline (plan §5).

Handlers have the signature handler(ctx, state, user) -> (status, body) and run while the
pipeline holds STORE.lock. Routes flagged locked=False get (ctx, None, None) and manage the
lock themselves (used for work that must stay outside the lock, e.g. password hashing).
"""
import re

from . import errors, idempotency
from .store import STORE

_ROUTES = []
IDEMPOTENCY_HEADER = "Idempotency-Key"


def route(method: str, pattern: str, auth: bool = True, idempotent: bool = False,
          operator: bool = False, locked: bool = True):
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def register(handler):
        _ROUTES.append({"method": method, "regex": regex, "handler": handler, "auth": auth,
                        "idempotent": idempotent, "operator": operator, "locked": locked})
        return handler
    return register


def _match(ctx):
    path_matched = False
    for r in _ROUTES:
        m = r["regex"].match(ctx.path)
        if not m:
            continue
        path_matched = True
        if r["method"] == ctx.method:
            ctx.params = m.groupdict()
            return r
    if path_matched:
        raise errors.ApiError(405, "method_not_allowed", "method not allowed on this path")
    raise errors.not_found("no such endpoint")


def authenticate(ctx, state):
    token = ctx.bearer_token()
    user_id = state["tokens"].get(token) if token else None
    if user_id is None or user_id not in state["users"]:
        raise errors.unauthenticated()
    return state["users"][user_id]


def _idempotency_key(ctx):
    key = ctx.header(IDEMPOTENCY_HEADER)
    if key is None or key == "":
        raise errors.ApiError(400, "missing_idempotency_key", "Idempotency-Key header required")
    if len(key) > 255:
        raise errors.validation("Idempotency-Key must be 1 to 255 characters")
    return key


def dispatch(ctx):
    r = _match(ctx)
    ctx.preparse()  # parse outside the lock; a parse error is raised later, in D-01 order
    if not r["locked"]:
        return r["handler"](ctx, None, None)
    # One hold: auth 401 -> operator 403 -> body 400 -> key 400/422 -> replay -> effect.
    with STORE.lock:
        state = STORE.state
        user = authenticate(ctx, state) if r["auth"] else None
        if r["operator"] and user["id"] not in state["operators"]:
            raise errors.forbidden("settlement operator required")
        if not r["idempotent"]:
            return r["handler"](ctx, state, user)
        body = ctx.json_object()
        key = _idempotency_key(ctx)
        slot = idempotency.slot(ctx.method, ctx.path, key)
        replay = idempotency.resolve(state, user["id"], slot, body)
        if replay is not None:
            return replay
        status, out = r["handler"](ctx, state, user)
        if status == 201:
            idempotency.record(state, user["id"], slot, body, out)
        return status, out
