"""The single state object, its single lock, and the only code that changes balances.

State holds JSON-native values only (dicts, lists, str, int, bool, None) so that it can be
exported as-is. Every function here that reads or writes `state` expects the caller to hold
`STORE.lock`, except `load_fixture`, which builds a fresh state off to the side.
"""
import secrets
import threading
from datetime import datetime, timezone

from . import errors, passwords
from .validation import BALANCE_LIMIT, HANDLE_RE, MAX_ID, VISIBILITIES, integral

REQUEST_STATUSES = ("pending", "paid", "declined", "cancelled")
ID_PREFIX = {"p": "p_", "rq": "rq_", "sp": "sp_", "st": "st_", "u": "u_"}
TABLE_FOR_KIND = {"p": "payments", "rq": "requests", "sp": "splits", "st": "settlements",
                  "u": "users"}


def empty_state(currency: str = "EUR", minor_units: int = 2) -> dict:
    return {
        "currency": currency, "minor_units": minor_units,
        "users": {}, "handles": {}, "emails": {}, "tokens": {}, "operators": [],
        "payments": {}, "payment_order": [], "requests": {}, "splits": {},
        "settlements": {}, "idem": {}, "seq": 0,
        "counters": {k: 0 for k in ID_PREFIX},
    }


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = empty_state()

    def replace_state(self, state: dict) -> None:
        with self.lock:
            self.state = state


STORE = Store()


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def user_by_handle(state: dict, handle: str):
    user_id = state["handles"].get(handle)
    return state["users"].get(user_id) if user_id else None


# ---------------------------------------------------------------- money movement

def _make_payment(state, from_id, to_id, amount, note, visibility, ts, request_id, settlement_id):
    payment = {
        "id": new_id(state, "p"), "from": from_id, "to": to_id, "amount": amount,
        "note": note, "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "created_at": ts, "seq": next_seq(state),
    }
    state["payments"][payment["id"]] = payment
    state["payment_order"].append(payment["id"])
    return payment


def apply_transfer(state, from_id, to_id, amount, note="", visibility="public",
                   request_id=None, ts=None):
    """Debit and credit in one step. Caller holds the lock. 409 if the payer is short."""
    users = state["users"]
    if users[from_id]["balance"] < amount:
        raise errors.conflict("insufficient_funds", "balance is below amount")
    users[from_id]["balance"] -= amount
    users[to_id]["balance"] += amount
    return _make_payment(state, from_id, to_id, amount, note, visibility, ts or now_ts(),
                         request_id, None)


def apply_batch(state, transfers, settlement_id, ts):
    """All-or-nothing batch: every wallet's net result must be >= 0. Caller holds the lock.

    transfers: list of dicts {from, to, amount, note, visibility}.
    """
    users = state["users"]
    net: dict = {}
    for t in transfers:
        net[t["from"]] = net.get(t["from"], 0) - t["amount"]
        net[t["to"]] = net.get(t["to"], 0) + t["amount"]
    if any(users[uid]["balance"] + delta < 0 for uid, delta in net.items()):
        raise errors.conflict("insufficient_funds", "settlement is not affordable")
    for uid, delta in net.items():
        users[uid]["balance"] += delta
    return [_make_payment(state, t["from"], t["to"], t["amount"], t["note"], t["visibility"],
                          ts, None, settlement_id) for t in transfers]


# ---------------------------------------------------------------- views

def payment_view(state: dict, p: dict) -> dict:
    users = state["users"]
    return {
        "payment_id": p["id"],
        "from_user_id": p["from"], "from_handle": users[p["from"]]["handle"],
        "to_user_id": p["to"], "to_handle": users[p["to"]]["handle"],
        "amount": p["amount"], "currency": state["currency"], "note": p["note"],
        "visibility": p["visibility"], "request_id": p["request_id"],
        "settlement_id": p["settlement_id"], "created_at": p["created_at"],
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


def _opt_ts(obj: dict, default: str) -> str:
    value = obj.get("created_at")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.isoformat(timespec="seconds")
        except ValueError:
            pass
    return default


def _load_users(state, users, ts):
    if not isinstance(users, list):
        _fail("users must be a list")
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
            "id": uid, "email": email, "password_hash": password,
            "display_name": display, "handle": handle, "balance": balance, "created_at": ts,
        }
        state["handles"][handle] = uid
        state["emails"][email.lower()] = uid
    # Hash only after the whole list validated, so a bad fixture costs no hashing.
    hashed = passwords.hash_many(u["password_hash"] for u in state["users"].values())
    for u in state["users"].values():
        u["password_hash"] = hashed[u["password_hash"]]


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
            "settlement_id": None, "created_at": _opt_ts(p, ts), "seq": next_seq(state),
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
            "created_at": _opt_ts(r, ts), "seq": next_seq(state),
        }


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
    operators = fixture.get("settlement_operator_ids", [])
    if not isinstance(operators, list) or any(
            not isinstance(o, str) or o not in state["users"] for o in operators):
        _fail("settlement_operator_ids must list known user ids")
    state["operators"] = list(dict.fromkeys(operators))
    return state
