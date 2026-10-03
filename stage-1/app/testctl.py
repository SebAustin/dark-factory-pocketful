"""GET /health and POST /_test/reset (spec §3.2, §3.3)."""
from .routes import route
from .store import STORE, load_fixture


@route("GET", "/health", auth=False)
def health(ctx, state, user):
    return 200, {"status": "ok"}


@route("POST", "/_test/reset", auth=False, locked=False)
def reset(ctx, state, user):
    # Validate and hash off to the side, then swap in one step: a failed reset changes nothing.
    fresh = load_fixture(ctx.json_object())
    STORE.replace_state(fresh)
    return 204, None
