"""GET /_test/export and POST /_test/import (spec §10).

Export is a JSON round trip of the state made while holding the lock, so the caller gets a private
snapshot. Import validates a fresh copy of the submitted state off to the side, then swaps it in
with one `replace_state`; an invalid state therefore changes nothing. Neither route needs a token.
"""
import json
from decimal import Decimal

from . import errors
from .routes import route
from .store import REQUEST_STATUSES, STORE, empty_state, parse_rfc3339
from .validation import BALANCE_LIMIT, HANDLE_RE, MAX_ID, VISIBILITIES, integral

TRACK = "pocketful"
FORMAT_VERSION = 1
MINOR_UNITS = (0, 2, 3)
COUNTER_KINDS = ("p", "rq", "sp", "st", "u")
STATE_KEYS = tuple(empty_state())


def _bad(message: str):
    raise errors.validation("state: " + message)


# ---------------------------------------------------------------- export

@route("GET", "/_test/export", auth=False, locked=False)
def export_state(ctx, state, user):
    with STORE.lock:
        snapshot = json.loads(json.dumps(STORE.state))
    return 200, {"track": TRACK, "format_version": FORMAT_VERSION, "state": snapshot}


# ---------------------------------------------------------------- validation helpers

def _native(value):
    """Copy of a parsed JSON value with Decimals turned into ints; fractions are invalid."""
    if isinstance(value, dict):
        return {k: _native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_native(v) for v in value]
    if isinstance(value, Decimal):
        n = integral(value)
        if n is None:
            _bad("non-integer number")
        return n
    return value


def _int(value, lo: int, hi: int, what: str) -> int:
    n = integral(value)
    if n is None or not lo <= n <= hi:
        _bad(what + " must be an integer from {} to {}".format(lo, hi))
    return n


def _dict(value, what: str) -> dict:
    if not isinstance(value, dict):
        _bad(what + " must be an object")
    return value


def _list(value, what: str) -> list:
    if not isinstance(value, list):
        _bad(what + " must be an array")
    return value


def _str(value, what: str, nonempty: bool = False) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _bad(what + " must be a " + ("non-empty " if nonempty else "") + "string")
    return value


def _opt_str(value, what: str):
    if value is not None and not isinstance(value, str):
        _bad(what + " must be a string or null")


def _timestamp(value, what: str) -> None:
    """RFC 3339 with an explicit offset, so every record sorts by its true instant."""
    if parse_rfc3339(value) is None:
        _bad(what + " must be an RFC 3339 timestamp with an offset")


def _opt_timestamps(table: dict, key: str, what: str) -> None:
    for rec in table.values():
        if key in rec:
            _timestamp(rec[key], what)


def _user_ref(users: dict, value, what: str) -> str:
    if not isinstance(value, str) or value not in users:
        _bad(what + " references an unknown user")
    return value


def _table(state: dict, name: str) -> dict:
    table = _dict(state[name], name)
    for key, rec in table.items():
        _dict(rec, name + " entry")
        if "id" in rec and rec["id"] != key:
            _bad(name + " entry id does not match its key")
    return table


# ---------------------------------------------------------------- validation by section

def _check_users(state: dict) -> None:
    users = _table(state, "users")
    seen_handles, seen_emails = {}, {}
    for uid, u in users.items():
        _str(uid, "user id", True)
        if len(uid) > MAX_ID or u.get("id") != uid:
            _bad("user id is invalid")
        _str(u.get("email"), "user email", True)
        _str(u.get("password_hash"), "user password_hash", True)
        _str(u.get("display_name"), "user display_name")
        handle = _str(u.get("handle"), "user handle")
        if not HANDLE_RE.match(handle):
            _bad("user handle has an invalid format")
        _int(u.get("balance"), 0, BALANCE_LIMIT, "user balance")
        if handle in seen_handles or u["email"].lower() in seen_emails:
            _bad("duplicate handle or email")
        seen_handles[handle] = uid
        seen_emails[u["email"].lower()] = uid
    if _dict(state["handles"], "handles") != seen_handles:
        _bad("handles index does not match users")
    if _dict(state["emails"], "emails") != seen_emails:
        _bad("emails index does not match users")


def _check_sessions(state: dict) -> None:
    users = state["users"]
    for token, uid in _dict(state["tokens"], "tokens").items():
        _str(token, "token", True)
        _user_ref(users, uid, "token")
    for uid in _list(state["operators"], "operators"):
        _user_ref(users, uid, "operator")


def _check_payments(state: dict) -> int:
    users, top = state["users"], 0
    for pid, p in _table(state, "payments").items():
        if p.get("id") != pid:
            _bad("payment id is missing")
        _user_ref(users, p.get("from"), "payment from")
        _user_ref(users, p.get("to"), "payment to")
        _int(p.get("amount"), 0, BALANCE_LIMIT, "payment amount")  # 0: paid zero-share request (D-11)
        _str(p.get("note"), "payment note")
        if p.get("visibility") not in VISIBILITIES:
            _bad("payment visibility is invalid")
        _opt_str(p.get("request_id"), "payment request_id")
        _opt_str(p.get("settlement_id"), "payment settlement_id")
        _timestamp(p.get("created_at"), "payment created_at")
        top = max(top, _int(p.get("seq"), 0, BALANCE_LIMIT, "payment seq"))
    order = _list(state["payment_order"], "payment_order")
    if any(not isinstance(i, str) for i in order) or sorted(order) != sorted(state["payments"]):
        _bad("payment_order does not list the payments exactly once")
    return top


def _check_requests(state: dict) -> int:
    users, top = state["users"], 0
    for rid, r in _table(state, "requests").items():
        if r.get("id") != rid:
            _bad("request id is missing")
        _user_ref(users, r.get("requester"), "request requester")
        _user_ref(users, r.get("payer"), "request payer")
        _int(r.get("amount"), 0, BALANCE_LIMIT, "request amount")  # 0: zero split share (§9)
        _str(r.get("note"), "request note")
        if r.get("status") not in REQUEST_STATUSES:
            _bad("request status is invalid")
        _opt_str(r.get("payment_id"), "request payment_id")
        _timestamp(r.get("created_at"), "request created_at")
        top = max(top, _int(r.get("seq"), 0, BALANCE_LIMIT, "request seq"))
    return top


def _check_idempotency(state: dict) -> None:
    for uid, slots in _dict(state["idem"], "idem").items():
        _user_ref(state["users"], uid, "idem")
        for slot, rec in _dict(slots, "idem slots").items():
            _str(slot, "idem slot", True)
            _dict(rec, "idem record")
            _str(rec.get("canon"), "idem canon")
            _dict(rec.get("body"), "idem body")


def _check_counters(state: dict, top_seq: int) -> None:
    if _int(state["seq"], 0, BALANCE_LIMIT, "seq") < top_seq:
        _bad("seq is behind a stored record")
    counters = _dict(state["counters"], "counters")
    for kind in COUNTER_KINDS:
        _int(counters.get(kind), 0, BALANCE_LIMIT, "counter " + kind)


def validated_state(submitted) -> dict:
    """Return a fresh, checked copy of an exported state, or raise 422."""
    state = _native(_dict(submitted, "state"))
    if any(key not in state for key in STATE_KEYS):
        _bad("a required key is missing")
    state = {key: state[key] for key in STATE_KEYS}  # unknown keys are ignored
    _str(state["currency"], "currency", True)
    if _int(state["minor_units"], 0, 3, "minor_units") not in MINOR_UNITS:
        _bad("minor_units must be 0, 2 or 3")
    _check_users(state)
    _check_sessions(state)
    top = max(_check_payments(state), _check_requests(state))
    _opt_timestamps(_table(state, "splits"), "created_at", "split created_at")
    _opt_timestamps(_table(state, "settlements"), "committed_at", "settlement committed_at")
    _opt_timestamps(state["users"], "created_at", "user created_at")
    _check_idempotency(state)
    _check_counters(state, top)
    return state


# ---------------------------------------------------------------- import

@route("POST", "/_test/import", auth=False, locked=False)
def import_state(ctx, state, user):
    body = ctx.json_object()
    if body.get("track") != TRACK or integral(body.get("format_version")) != FORMAT_VERSION \
            or isinstance(body.get("format_version"), bool):
        raise errors.validation("track must be pocketful and format_version 1")
    if "state" not in body:
        raise errors.validation("state is required")
    fresh = validated_state(body["state"])
    STORE.replace_state(fresh)  # one lock hold: all of the old state goes, all of the new arrives
    return 204, None
