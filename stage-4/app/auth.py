"""Signup, login and GET /me (spec §6, §4 handles, §8)."""
import re

from . import errors, instants, ledger, passwords
from .routes import route
from .store import STORE, available, new_id, new_token, now_ts
from .validation import query_instant, req_str

EMAIL_RE = re.compile(r"\A[^@\s]+@[^@\s]+\Z")
NON_HANDLE_RE = re.compile(r"[^a-z0-9_]")
MIN_PASSWORD = 8
MAX_HANDLE = 20


def derive_handle(email: str) -> str:
    local = email.rsplit("@", 1)[0]
    return NON_HANDLE_RE.sub("_", local.lower())[:MAX_HANDLE]


def _credentials(body: dict):
    email = req_str(body, "email")
    password = req_str(body, "password")
    return email, password


def _check_free(state: dict, email: str, handle: str) -> None:
    if email.lower() in state["emails"]:
        raise errors.conflict("email_taken", "email already registered")
    if handle in state["handles"]:
        raise errors.conflict("handle_taken", "derived handle already taken")


def _session(user: dict, token: str) -> dict:
    return {"user_id": user["id"], "display_name": user["display_name"], "token": token}


@route("POST", "/auth/signup", auth=False, locked=False)
def signup(ctx, state, user):
    body = ctx.json_object()
    email, password = _credentials(body)
    display_name = req_str(body, "display_name")
    if not EMAIL_RE.match(email):
        raise errors.validation("email must be of the form local@domain")
    if len(password) < MIN_PASSWORD:
        raise errors.validation("password must be at least 8 characters")
    handle = derive_handle(email)
    with STORE.hold():
        _check_free(STORE.state, email, handle)  # fail fast before the slow hash
    password_hash = passwords.hash_password(password)  # slow: outside the lock
    with STORE.hold():
        state = STORE.state
        _check_free(state, email, handle)  # re-check: the state may have changed meanwhile
        uid = new_id(state, "u")
        created = {"id": uid, "email": email, "password_hash": password_hash,
                   "display_name": display_name, "handle": handle, "balance": 0, "held": 0, "opening": 0,
                   "created_at": now_ts()}
        state["users"][uid] = created
        state["handles"][handle] = uid
        state["emails"][email.lower()] = uid
        state["user_payments"][uid] = []
        return 201, _session(created, new_token(state, uid))


@route("POST", "/auth/login", auth=False, locked=False)
def login(ctx, state, user):
    email, password = _credentials(ctx.json_object())
    with STORE.hold():
        state = STORE.state
        uid = state["emails"].get(email.lower())
        stored = state["users"][uid]["password_hash"] if uid else None
    if stored is None or not passwords.verify_password(password, stored):
        raise errors.unauthenticated("wrong email or password")
    with STORE.hold():
        state = STORE.state
        found = state["users"].get(uid)
        # A reset between the two holds may have replaced this account.
        if found is None or found["password_hash"] != stored:
            raise errors.unauthenticated("wrong email or password")
        return 200, _session(found, new_token(state, uid))


@route("GET", "/me")
def me(ctx, state, user):
    as_of = query_instant(ctx.query, "as_of")
    known_at = query_instant(ctx.query, "known_at")
    if as_of is None and known_at is None:  # stage 2 response, current corrected values
        total, held = user["balance"], user.get("held", 0)
    else:  # one read instant N for every default of this read (D-43)
        now = instants.key(now_ts())
        at = as_of[1] if as_of else now
        known = known_at[1] if known_at else now
        total = ledger.total_at(state, user["id"], at, known)
        held = ledger.held_at(state, user["id"], at, known)
    body = {"user_id": user["id"], "display_name": user["display_name"],
            "handle": user["handle"], "balance": total, "total": total,
            "available": total - held, "held": held,
            "currency": state["currency"], "minor_units": state["minor_units"]}
    if as_of:
        body["as_of"] = as_of[0]
    if known_at:
        body["known_at"] = known_at[0]
    return 200, body
