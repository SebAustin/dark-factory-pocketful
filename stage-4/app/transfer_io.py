"""GET /_test/export and POST /_test/import (spec §10).

Export is a JSON round trip of the state made while holding the lock, so the caller gets a private
snapshot. Import validates a fresh copy of the submitted state off to the side, then swaps it in
with one `replace_state`; an invalid state therefore changes nothing. Neither route needs a token.
"""
import json
from decimal import Decimal

from . import errors
from .routes import route
from . import instants, ledger, statements, store
from .store import (AUTH_STATUSES, DEFAULT_TTL, REQUEST_STATUSES, STORE, empty_state,
                    parse_rfc3339)
from .validation import BALANCE_LIMIT, HANDLE_RE, MAX_ID, VISIBILITIES, integral

TRACK = "pocketful"
FORMAT_VERSION = 1
MINOR_UNITS = (0, 2, 3)
COUNTER_KINDS = ("p", "rq", "sp", "st", "u")
# Stage 2 keys a stage-1 export does not have: filled with these defaults on import (D10).
STAGE2_DEFAULTS = {"authorizations": {}, "settings": {"authorization_ttl_seconds": DEFAULT_TTL},
                   "correction_batches": {}}  # (stage 4 key; older exports have none)
DERIVED_KEYS = ("user_payments", "refunds_of")  # rebuilt on import, never trusted
STATE_KEYS = tuple(k for k in empty_state()
                   if k not in STAGE2_DEFAULTS and k not in DERIVED_KEYS)
EVENT_KINDS = ("created", "capture", "release")
MAX_EXPONENT = 18  # 2^53 has 16 digits; anything past 1e18 can never be a valid state value


def _bad(message: str):
    raise errors.validation("state: " + message)


# ---------------------------------------------------------------- export

@route("GET", "/_test/export", auth=False, locked=False)
def export_state(ctx, state, user):
    with STORE.hold():
        snapshot = json.loads(json.dumps(STORE.state))
        # L10: statement snapshots travel with the state (exact decimal keys as strings)
        snapshot["snapshots"] = json.loads(json.dumps(statements.export_snapshots(STORE.state)))
    return 200, {"track": TRACK, "format_version": FORMAT_VERSION, "state": snapshot}


# ---------------------------------------------------------------- validation helpers

def _native(value):
    """Copy of a parsed JSON value with Decimals turned into ints; fractions are invalid."""
    if isinstance(value, dict):
        return {k: _native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_native(v) for v in value]
    if isinstance(value, Decimal):
        # Refuse absurd exponents before int() could build a billion-digit integer.
        if not value.is_finite() or not -MAX_EXPONENT <= value.adjusted() <= MAX_EXPONENT:
            _bad("number out of range")
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
    counters["a"] = _int(counters.get("a", 0), 0, BALANCE_LIMIT, "counter a")
    counters["cb"] = _int(counters.get("cb", 0), 0, BALANCE_LIMIT, "counter cb")


def _check_settings(state: dict) -> None:
    settings = _dict(state["settings"], "settings")
    ttl = store.valid_ttl(settings.get("authorization_ttl_seconds", DEFAULT_TTL))
    if ttl is None:
        _bad("authorization_ttl_seconds must be a positive integer within datetime's range")
    state["settings"] = {"authorization_ttl_seconds": ttl}


def _check_authorizations(state: dict) -> int:
    users, top = state["users"], 0
    for aid, a in _table(state, "authorizations").items():
        if a.get("id") != aid or len(aid) > MAX_ID:
            _bad("authorization id is missing")
        _user_ref(users, a.get("from"), "authorization from")
        _user_ref(users, a.get("to"), "authorization to")
        if a["from"] == a["to"]:
            _bad("authorization parties must differ")
        amount = _int(a.get("amount"), 1, BALANCE_LIMIT, "authorization amount")
        _int(a.get("captured"), 0, amount, "authorization captured")
        _str(a.get("note"), "authorization note")
        if a.get("visibility") not in VISIBILITIES or a.get("status") not in AUTH_STATUSES:
            _bad("authorization visibility or status is invalid")
        _timestamp(a.get("expires_at"), "authorization expires_at")
        _timestamp(a.get("created_at"), "authorization created_at")
        ids = _list(a.get("payment_ids"), "authorization payment_ids")
        if any(not isinstance(i, str) for i in ids):
            _bad("authorization payment_ids must be strings")
        top = max(top, _int(a.get("seq"), 0, BALANCE_LIMIT, "authorization seq"))
    return top


def _check_revisions(state: dict) -> None:
    """Stage 3 revisions when present (else synthesised: revision 1 = the payment as made)."""
    for p in state["payments"].values():
        if "revisions" not in p:
            p["revisions"] = [ledger.revision_one(p)]
            continue
        revs = _list(p["revisions"], "payment revisions")
        if not revs:
            _bad("payment revisions must not be empty")
        last = None
        for i, r in enumerate(revs, start=1):
            _dict(r, "revision")
            if _int(r.get("revision"), 1, BALANCE_LIMIT, "revision number") != i:
                _bad("revision numbers must be 1, 2, ...")
            _int(r.get("amount"), 0, BALANCE_LIMIT, "revision amount")
            _timestamp(r.get("effective_at"), "revision effective_at")
            _timestamp(r.get("recorded_at"), "revision recorded_at")
            _str(r.get("reason"), "revision reason")
            k = instants.key(r["recorded_at"])
            if last is not None and k <= last:
                _bad("revision recorded_at must strictly increase")
            last = k
        if revs[0]["amount"] != p["amount"]:
            _bad("revision 1 must be the payment as made")


def _reconstruct_events(state: dict, a: dict) -> None:
    """Hold lifecycle for an authorization exported before stage 3 (plan §5, S3-D7)."""
    events, at = [], a["created_at"]
    events.append({"kind": "created", "at": at, "held_delta": a["amount"], "payment_id": None})
    captured = 0
    for pid in a["payment_ids"]:
        p = state["payments"].get(pid)
        if p is None:
            _bad("authorization payment_ids must name payments")
        captured += p["amount"]
        at = p["created_at"]
        events.append({"kind": "capture", "at": at, "held_delta": -p["amount"],
                       "payment_id": pid})
    a["closed_at"] = None
    if a["status"] != "open":
        # expired: at its deadline; captured: at the last capture; voided: the void time was
        # not exported by stage 2, so the earliest consistent release, its latest known event.
        close = a["expires_at"] if a["status"] == "expired" else at
        rest = a["amount"] - captured
        if rest > 0:
            events.append({"kind": "release", "at": close, "held_delta": -rest,
                           "payment_id": None})
        a["closed_at"] = close
    a["events"] = events


def _check_events(state: dict) -> None:
    for a in state["authorizations"].values():
        if "events" not in a:
            _reconstruct_events(state, a)
            continue
        for e in _list(a["events"], "authorization events"):
            _dict(e, "authorization event")
            if e.get("kind") not in EVENT_KINDS:
                _bad("authorization event kind is invalid")
            _timestamp(e.get("at"), "authorization event at")
            _int(e.get("held_delta"), -BALANCE_LIMIT, BALANCE_LIMIT, "event held_delta")
            _opt_str(e.get("payment_id"), "event payment_id")
        if a.get("closed_at") is not None:
            _timestamp(a["closed_at"], "authorization closed_at")
        a.setdefault("closed_at", None)


def is_upgrade_state(submitted) -> bool:
    """A stage-1, -2 or -3 export (no stage 4 keys): the upgrade path (L5, D-52, D-74)."""
    return isinstance(submitted, dict) and "correction_batches" not in submitted


def carry_sessions(old: dict, new: dict) -> None:
    """L5 (D-22): on a stage-1 upgrade import, keep each destination token whose user exists in
    the imported state with the same id, email (case-insensitive) and handle. Tokens in the
    export always win; every other destination token is dropped."""
    for token, uid in old["tokens"].items():
        if token in new["tokens"]:
            continue
        before, after = old["users"].get(uid), new["users"].get(uid)
        if before and after and before["email"].lower() == after["email"].lower() \
                and before["handle"] == after["handle"]:
            new["tokens"][token] = uid


def validated_state(submitted) -> dict:
    """Return a fresh, checked copy of an exported state, or raise 422."""
    full = _native(_dict(submitted, "state"))
    if any(key not in full for key in STATE_KEYS):
        _bad("a required key is missing")
    state = {key: full[key] for key in STATE_KEYS}  # unknown keys are ignored
    for key, default in STAGE2_DEFAULTS.items():  # older exports lack these
        state[key] = full[key] if key in full else json.loads(json.dumps(default))
    _str(state["currency"], "currency", True)
    if _int(state["minor_units"], 0, 3, "minor_units") not in MINOR_UNITS:
        _bad("minor_units must be 0, 2 or 3")
    _check_users(state)
    _check_sessions(state)
    _check_settings(state)
    top = max(_check_payments(state), _check_requests(state), _check_authorizations(state))
    _opt_timestamps(_table(state, "splits"), "created_at", "split created_at")
    _opt_timestamps(_table(state, "settlements"), "committed_at", "settlement committed_at")
    _opt_timestamps(state["users"], "created_at", "user created_at")
    _check_idempotency(state)
    _check_counters(state, top)
    for p in state["payments"].values():
        p.setdefault("authorization_id", None)
        _opt_str(p["authorization_id"], "payment authorization_id")
        p.setdefault("refund_of", None)  # stage 4; older exports have no refunds
        if p["refund_of"] is not None and p["refund_of"] not in state["payments"]:
            _bad("payment refund_of must name a payment")
    _check_revisions(state)
    _check_events(state)
    for batch in _table(state, "correction_batches").values():  # stage 4
        _str(batch.get("recorded_at"), "correction batch recorded_at", True)
    store.recompute_held(state, store.now_key())  # held is derived, never trusted (plan §5)
    ledger.rebuild_user_payments(state)
    ledger.compute_openings(state)
    # D-52: no history validation on import; the source service enforced its own rules.
    if any(u["held"] > u["balance"] for u in state["users"].values()):
        _bad("open holds exceed a balance (available would be negative)")
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
    submitted = body["state"]
    snapshots = statements.import_snapshots(submitted["snapshots"], fresh) \
        if "snapshots" in submitted else {}  # stage-1/2/3 exports carry none (L10)
    upgrade = is_upgrade_state(submitted)

    def carry(old: dict, new: dict) -> None:
        # One lock hold: all of the old state goes, all of the new arrives. Upgrades keep the
        # destination's signed-in sessions (L5, D-74); imported snapshots merge into the
        # process store, the imported token winning a clash (L10, L12).
        if upgrade:
            carry_sessions(old, new)
        STORE.snapshots.update(snapshots)
    STORE.replace_state(fresh, carry=carry)
    return 204, None
