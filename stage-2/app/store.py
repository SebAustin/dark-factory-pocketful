"""The single state object, its single lock, and the only code that changes balances.

State holds JSON-native values only (dicts, lists, str, int, bool, None) so that it can be
exported as-is. Every function here that reads or writes `state` expects the caller to hold
`STORE.lock`, except `load_fixture`, which builds a fresh state off to the side.
"""
import heapq
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import errors, passwords
from .validation import BALANCE_LIMIT, HANDLE_RE, MAX_ID, VISIBILITIES, integral

REQUEST_STATUSES = ("pending", "paid", "declined", "cancelled")
AUTH_STATUSES = ("open", "captured", "voided", "expired")
DEFAULT_TTL = 600
MAX_TTL = 10 ** 9   # D9: keeps created_at + ttl inside datetime's range
MAX_AMOUNT = 1_000_000_000
ID_PREFIX = {"p": "p_", "rq": "rq_", "sp": "sp_", "st": "st_", "u": "u_", "a": "a_"}
TABLE_FOR_KIND = {"p": "payments", "rq": "requests", "sp": "splits", "st": "settlements",
                  "u": "users", "a": "authorizations"}

clock = time.time  # seconds since the epoch; tests may replace it


def empty_state(currency: str = "EUR", minor_units: int = 2) -> dict:
    return {
        "currency": currency, "minor_units": minor_units,
        "users": {}, "handles": {}, "emails": {}, "tokens": {}, "operators": [],
        "payments": {}, "payment_order": [], "requests": {}, "splits": {},
        "settlements": {}, "idem": {}, "seq": 0,
        "counters": {k: 0 for k in ID_PREFIX},
        "authorizations": {}, "settings": {"authorization_ttl_seconds": DEFAULT_TTL},
    }


class Store:
    """The state, its lock, and the expiry queue of open holds (not part of the state)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = empty_state()
        self._due: list = []  # heap of (expires instant, authorization id)

    def replace_state(self, state: dict) -> None:
        due = [(instant(a["expires_at"]), aid)
               for aid, a in state.get("authorizations", {}).items() if a["status"] == "open"]
        heapq.heapify(due)
        with self.lock:
            self.state = state
            self._due = due

    def schedule(self, authorization: dict) -> None:
        """Queue an open hold for expiry. Caller holds the lock."""
        heapq.heappush(self._due, (instant(authorization["expires_at"]), authorization["id"]))

    @contextmanager
    def hold(self):
        """The lock, with every hold whose expires_at is at or before now expired first.

        Every read and write of the state goes through here, so expiry is visible at every read
        even if no request happened at the deadline.
        """
        with self.lock:
            self._sweep(clock())
            yield self.state

    def _sweep(self, now: float) -> None:
        while self._due and self._due[0][0] <= now:
            _, aid = heapq.heappop(self._due)
            a = self.state["authorizations"].get(aid)
            if a is not None and a["status"] == "open" and instant(a["expires_at"]) <= now:
                expire_authorization(self.state, a)


STORE = Store()


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


RFC3339_RE = re.compile(
    r"\A\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(\.\d+)?([Zz]|[+-]\d\d:\d\d)\Z")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_rfc3339(value):
    """Parse an RFC 3339 timestamp with an explicit offset; None if it is not one."""
    if not isinstance(value, str) or not RFC3339_RE.match(value):
        return None
    try:
        return datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        return None


@lru_cache(maxsize=65536)
def instant(ts: str) -> float:
    """Seconds since the epoch for a stored created_at (any offset). Never raises."""
    parsed = parse_rfc3339(ts)
    return (parsed - _EPOCH).total_seconds() if parsed else float("-inf")


def newest_first(records):
    """The one ordering rule for every list: newest instant first, ties by creation order."""
    return sorted(records, key=lambda r: (instant(r["created_at"]), r["seq"]), reverse=True)


def next_seq(state: dict) -> int:
    state["seq"] += 1
    return state["seq"]


def new_id(state: dict, kind: str) -> str:
    table = state[TABLE_FOR_KIND[kind]]
    while True:
        state["counters"][kind] += 1
        candidate = ID_PREFIX[kind] + str(state["counters"][kind])
        if candidate not in table:
            return candidate


def new_token(state: dict, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    state["tokens"][token] = user_id
    return token


def available(user: dict) -> int:
    """available = total - held (stage 2). total is the stage 1 `balance`."""
    return user["balance"] - user.get("held", 0)


def user_by_handle(state: dict, handle: str):
    user_id = state["handles"].get(handle)
    return state["users"].get(user_id) if user_id else None


# ---------------------------------------------------------------- money movement

def _make_payment(state, from_id, to_id, amount, note, visibility, ts, request_id, settlement_id,
                  authorization_id=None):
    payment = {
        "id": new_id(state, "p"), "from": from_id, "to": to_id, "amount": amount,
        "note": note, "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "authorization_id": authorization_id,
        "created_at": ts, "seq": next_seq(state),
    }
    state["payments"][payment["id"]] = payment
    state["payment_order"].append(payment["id"])
    return payment


def apply_transfer(state, from_id, to_id, amount, note="", visibility="public",
                   request_id=None, ts=None):
    """Debit and credit in one step. Caller holds the lock. 409 if available is short."""
    users = state["users"]
    if available(users[from_id]) < amount:
        raise errors.conflict("insufficient_funds", "available balance is below amount")
    users[from_id]["balance"] -= amount
    users[to_id]["balance"] += amount
    return _make_payment(state, from_id, to_id, amount, note, visibility, ts or now_ts(),
                         request_id, None)


def apply_batch(state, transfers, settlement_id, ts):
    """All-or-nothing batch: every wallet's available + net must be >= 0. Caller holds the lock.

    transfers: list of dicts {from, to, amount, note, visibility}.
    """
    users = state["users"]
    net: dict = {}
    for t in transfers:
        net[t["from"]] = net.get(t["from"], 0) - t["amount"]
        net[t["to"]] = net.get(t["to"], 0) + t["amount"]
    if any(available(users[uid]) + delta < 0 for uid, delta in net.items()):
        raise errors.conflict("insufficient_funds", "settlement is not affordable")
    for uid, delta in net.items():
        users[uid]["balance"] += delta
    return [_make_payment(state, t["from"], t["to"], t["amount"], t["note"], t["visibility"],
                          ts, None, settlement_id) for t in transfers]


# ---------------------------------------------------------------- holds (stage 2)
# held changes only here: create (+amount), capture (-captured, -remainder if final),
# void and expiry (-remainder). Reset and import recompute it from the table.

def remaining(a: dict) -> int:
    return a["amount"] - a["captured"] if a["status"] == "open" else 0


def _close(state: dict, a: dict, status: str) -> None:
    state["users"][a["from"]]["held"] -= remaining(a)
    a["status"] = status


def expire_authorization(state: dict, a: dict) -> None:
    _close(state, a, "expired")


def void_authorization(state: dict, a: dict) -> None:
    _close(state, a, "voided")


def place_hold(state, from_id, to_id, amount, note, visibility):
    """Reserve amount of from_id's available funds. Caller holds STORE.hold(). 409 if short."""
    payer = state["users"][from_id]
    if available(payer) < amount:
        raise errors.conflict("insufficient_funds", "available balance is below amount")
    created = datetime.fromtimestamp(int(clock()), timezone.utc)
    ttl = state["settings"]["authorization_ttl_seconds"]
    a = {
        "id": new_id(state, "a"), "from": from_id, "to": to_id, "amount": amount,
        "captured": 0, "note": note, "visibility": visibility, "status": "open",
        "expires_at": (created + timedelta(seconds=ttl)).isoformat(),
        "created_at": created.isoformat(), "seq": next_seq(state), "payment_ids": [],
    }
    state["authorizations"][a["id"]] = a
    payer["held"] = payer.get("held", 0) + amount
    STORE.schedule(a)
    return a


def is_expired(a: dict) -> bool:
    return a["status"] == "expired" or (a["status"] == "open"
                                        and instant(a["expires_at"]) <= clock())


def recompute_held(state: dict, now: float) -> None:
    """Derive every user's held from the open holds; open holds already past expire here."""
    for u in state["users"].values():
        u["held"] = 0
    for a in state["authorizations"].values():
        if a["status"] == "open" and instant(a["expires_at"]) <= now:
            a["status"] = "expired"
        if a["status"] == "open":
            state["users"][a["from"]]["held"] += remaining(a)


# ---------------------------------------------------------------- views

def payment_view(state: dict, p: dict) -> dict:
    users = state["users"]
    return {
        "payment_id": p["id"],
        "from_user_id": p["from"], "from_handle": users[p["from"]]["handle"],
        "to_user_id": p["to"], "to_handle": users[p["to"]]["handle"],
        "amount": p["amount"], "currency": state["currency"], "note": p["note"],
        "visibility": p["visibility"], "request_id": p["request_id"],
        "settlement_id": p["settlement_id"], "authorization_id": p.get("authorization_id"),
        "created_at": p["created_at"],
    }


def request_view(state: dict, r: dict) -> dict:
    users = state["users"]
    return {
        "request_id": r["id"],
        "requester_id": r["requester"], "requester_handle": users[r["requester"]]["handle"],
        "payer_id": r["payer"], "payer_handle": users[r["payer"]]["handle"],
        "amount": r["amount"], "currency": state["currency"], "note": r["note"],
        "status": r["status"], "payment_id": r["payment_id"], "created_at": r["created_at"],
    }


# ---------------------------------------------------------------- fixture loading

def _fail(message: str):
    raise errors.validation("fixture: " + message)


def _need(obj: dict, name: str, kind, where: str):
    if not isinstance(obj, dict) or name not in obj or not isinstance(obj[name], kind) \
            or isinstance(obj[name], bool):
        _fail("{} needs {} of type {}".format(where, name, kind.__name__))
    return obj[name]


def _need_id(obj: dict, name: str, where: str) -> str:
    value = _need(obj, name, str, where)
    if not value or len(value) > MAX_ID:
        _fail(where + " has an invalid " + name)
    return value


def _need_int(obj: dict, name: str, where: str, lo: int, hi: int) -> int:
    n = integral(obj.get(name)) if isinstance(obj, dict) else None
    if n is None or n < lo or n > hi:
        _fail("{} has an invalid {}".format(where, name))
    return n


def _opt_str(obj: dict, name: str, default: str, where: str) -> str:
    if name not in obj or obj[name] is None:
        return default
    if not isinstance(obj[name], str):
        _fail(where + " has an invalid " + name)
    return obj[name]


def _opt_ts(obj: dict, default: str, where: str) -> str:
    """Fixture created_at: absent/null -> reset time; else RFC 3339 with an offset or 422."""
    value = obj.get("created_at")
    if value is None:
        return default
    parsed = parse_rfc3339(value)
    if parsed is None:
        _fail(where + " has a created_at that is not RFC 3339 with an offset")
    return parsed.isoformat()


def _load_users(state, users, ts):
    if not isinstance(users, list):
        _fail("users must be a list")
    plaintext: dict = {}  # user id -> password, only until hashed below
    for u in users:
        uid = _need_id(u, "id", "user")
        email = _need(u, "email", str, "user")
        password = _need(u, "password", str, "user")
        display = _need(u, "display_name", str, "user")
        handle = _need(u, "handle", str, "user")
        balance = _need_int(u, "balance", "user " + uid, 0, BALANCE_LIMIT)
        if not HANDLE_RE.match(handle):
            _fail("invalid handle " + handle)
        if uid in state["users"] or handle in state["handles"] or email.lower() in state["emails"]:
            _fail("duplicate user id, handle or email for " + uid)
        state["users"][uid] = {
            "id": uid, "email": email, "password_hash": None,
            "display_name": display, "handle": handle, "balance": balance, "held": 0,
            "created_at": ts,
        }
        state["handles"][handle] = uid
        state["emails"][email.lower()] = uid
        plaintext[uid] = password
    # Hash only after the whole list validated, so a bad fixture costs no hashing.
    hashed = passwords.hash_many(plaintext.values())
    for uid, password in plaintext.items():
        state["users"][uid]["password_hash"] = hashed[password]


def _load_payments(state, payments, ts):
    if not isinstance(payments, list):
        _fail("payments must be a list")
    for p in payments:
        pid = _need_id(p, "id", "payment")
        src, dst = _need(p, "from_user_id", str, pid), _need(p, "to_user_id", str, pid)
        if pid in state["payments"] or src not in state["users"] or dst not in state["users"]:
            _fail("payment {} is duplicate or references an unknown user".format(pid))
        vis = _opt_str(p, "visibility", "public", pid)
        if vis not in VISIBILITIES:
            _fail("payment {} has an invalid visibility".format(pid))
        state["payments"][pid] = {
            "id": pid, "from": src, "to": dst,
            "amount": _need_int(p, "amount", pid, 1, BALANCE_LIMIT),
            "note": _opt_str(p, "note", "", pid), "visibility": vis,
            "request_id": p.get("request_id") if isinstance(p.get("request_id"), str) else None,
            "settlement_id": None, "authorization_id": None,
            "created_at": _opt_ts(p, ts, pid), "seq": next_seq(state),
        }
        state["payment_order"].append(pid)


def _load_requests(state, requests, ts):
    if not isinstance(requests, list):
        _fail("requests must be a list")
    for r in requests:
        rid = _need_id(r, "id", "request")
        src, dst = _need(r, "requester_id", str, rid), _need(r, "payer_id", str, rid)
        if rid in state["requests"] or src not in state["users"] or dst not in state["users"]:
            _fail("request {} is duplicate or references an unknown user".format(rid))
        status = _opt_str(r, "status", "pending", rid)
        if status not in REQUEST_STATUSES:
            _fail("request {} has an invalid status".format(rid))
        state["requests"][rid] = {
            "id": rid, "requester": src, "payer": dst,
            "amount": _need_int(r, "amount", rid, 1, BALANCE_LIMIT),
            "note": _opt_str(r, "note", "", rid), "status": status,
            "payment_id": r.get("payment_id") if isinstance(r.get("payment_id"), str) else None,
            "created_at": _opt_ts(r, ts, rid), "seq": next_seq(state),
        }


def _need_ts(obj: dict, name: str, where: str) -> str:
    parsed = parse_rfc3339(obj.get(name)) if isinstance(obj, dict) else None
    if parsed is None:
        _fail("{} needs {} as RFC 3339 with an offset".format(where, name))
    return parsed.isoformat()


def _load_ttl(state, fixture):
    if "authorization_ttl_seconds" not in fixture:
        return
    ttl = integral(fixture["authorization_ttl_seconds"])
    if ttl is None or not 1 <= ttl <= MAX_TTL:
        _fail("authorization_ttl_seconds must be a positive integer number of seconds")
    state["settings"]["authorization_ttl_seconds"] = ttl


def _load_authorizations(state, authorizations, ts):
    if not isinstance(authorizations, list):
        _fail("authorizations must be a list")
    for a in authorizations:
        aid = _need_id(a, "id", "authorization")
        src, dst = _need(a, "from_user_id", str, aid), _need(a, "to_user_id", str, aid)
        if aid in state["authorizations"] or src not in state["users"] \
                or dst not in state["users"] or src == dst:
            _fail("authorization {} is duplicate or has invalid parties".format(aid))
        amount = _need_int(a, "amount", aid, 1, MAX_AMOUNT)
        captured = _need_int(a, "captured_amount", aid, 0, amount) \
            if a.get("captured_amount") is not None else 0
        status = _need(a, "status", str, aid)
        vis = _opt_str(a, "visibility", "public", aid)
        note = _opt_str(a, "note", "", aid)
        if status not in AUTH_STATUSES or vis not in VISIBILITIES or len(note) > 200:
            _fail("authorization {} has an invalid status, visibility or note".format(aid))
        ids = a.get("payment_ids")
        if ids is None:
            ids = [a["payment_id"]] if isinstance(a.get("payment_id"), str) else []
        if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
            _fail("authorization {} has invalid payment_ids".format(aid))
        state["authorizations"][aid] = {
            "id": aid, "from": src, "to": dst, "amount": amount, "captured": captured,
            "note": note, "visibility": vis, "status": status,
            "expires_at": _need_ts(a, "expires_at", aid), "created_at": _opt_ts(a, ts, aid),
            "seq": next_seq(state), "payment_ids": list(ids),
        }
    recompute_held(state, clock())
    for u in state["users"].values():
        if u["held"] > u["balance"]:
            _fail("open holds of {} exceed its balance".format(u["id"]))


def load_fixture(fixture: dict) -> dict:
    """Validate a reset fixture (spec §4) into a fresh state. Raises 422 on any problem."""
    currency = fixture.get("currency")
    if not isinstance(currency, str) or not currency:
        _fail("currency must be a non-empty string")
    minor_units = integral(fixture.get("minor_units"))
    if minor_units not in (0, 2, 3):
        _fail("minor_units must be 0, 2 or 3")
    state = empty_state(currency, minor_units)
    ts = now_ts()
    _load_users(state, fixture.get("users", []), ts)
    _load_payments(state, fixture.get("payments", []), ts)
    _load_requests(state, fixture.get("requests", []), ts)
    _load_ttl(state, fixture)
    _load_authorizations(state, fixture.get("authorizations", []), ts)
    operators = fixture.get("settlement_operator_ids", [])
    if not isinstance(operators, list) or any(
            not isinstance(o, str) or o not in state["users"] for o in operators):
        _fail("settlement_operator_ids must list known user ids")
    state["operators"] = list(dict.fromkeys(operators))
    return state
