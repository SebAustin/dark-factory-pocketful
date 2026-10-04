"""GET /statement and its snapshots (stage 3; D-48, D-49, D-50, D-54).

A first read freezes a *recipe* — (user, from, resolved to, K' = min(known_at, N), the known_at
echo, and the ledger state object it read) — and returns a page of its result. A snapshot read
recomputes from the recipe. That reproduces the first result exactly: payments and revisions are
append-only and never edited in place, every later write is recorded after N, so selection at
K' <= N sees the same revisions. O(1) memory per snapshot; not exported; only reset ends them
(D-50, final L8). An import swaps in a new state object; recipes keep the one they read.
"""
import secrets

from . import errors, instants, validation
from .ledger import selected, signed
from .payments import page
from .routes import route
from .store import STORE, now_ts, payment_view

WINDOW_PARAMS = ("from", "to", "known_at")


def _compute(state: dict, uid: str, start, end, known) -> dict:
    """D-48 step 4 over [start, end) as known at `known` (keys; start may be -inf)."""
    opening = state["users"][uid]["opening"]
    window = []
    for pid in state["user_payments"].get(uid, ()):
        p = state["payments"][pid]
        rev = selected(p, known)
        if rev is None:
            continue
        when = instants.key_or_min(rev["effective_at"])
        delta = signed(uid, p, rev["amount"])
        if when < start:
            opening += delta
        elif when < end:
            window.append((when, pid, rev["revision"], delta))
    window.sort(key=lambda w: (w[0], w[1]))  # effective_at, then payment id by code point
    entries, running = [], opening
    for _, pid, revision, delta in window:
        running += delta
        entries.append([pid, revision, delta, running])
    return {"user": uid, "opening_balance": opening, "closing_balance": running,
            "entries": entries}


def _render(state: dict, snap: dict, token: str, limit: int, offset: int) -> dict:
    rows = snap["entries"][offset:offset + limit]
    entries = []
    for pid, revision, delta, balance_after in rows:
        p = state["payments"][pid]
        rev = p["revisions"][revision - 1]
        view = payment_view(state, p)
        view["amount"] = rev["amount"]  # the selected amount for this statement (D-47)
        entries.append({"payment": view, "delta": delta, "revision": revision,
                        "effective_at": rev["effective_at"], "recorded_at": rev["recorded_at"],
                        "balance_after": balance_after})
    body = {"opening_balance": snap["opening_balance"], "entries": entries,
            "closing_balance": snap["closing_balance"],
            "has_more": offset + limit < len(snap["entries"]), "snapshot": token}
    if snap.get("known_at") is not None:
        body["known_at"] = snap["known_at"]
    return body


def _limit_offset(query: dict):
    limit = validation.query_int(query, "limit", 50, 1, 200)
    offset = validation.query_int(query, "offset", 0, 0)
    return limit, offset


def _page(snap: dict, token: str, limit: int, offset: int) -> dict:
    state = snap["state"]
    result = _compute(state, snap["user"], snap["start"], snap["end"], snap["known"])
    result["known_at"] = snap["known_echo"]
    return _render(state, result, token, limit, offset)


@route("GET", "/statement")
def statement(ctx, state, user):
    query = ctx.query
    if "snapshot" in query:
        if any(name in query for name in WINDOW_PARAMS):
            raise errors.validation("only limit and offset may accompany a snapshot")
        limit, offset = _limit_offset(query)
        snap = STORE.snapshots.get(query["snapshot"])
        if snap is None or snap["user"] != user["id"]:
            raise errors.not_found("no such snapshot")
        return 200, _page(snap, query["snapshot"], limit, offset)
    start = validation.query_instant(query, "from")
    end = validation.query_instant(query, "to")
    known = validation.query_instant(query, "known_at")
    if start and end and start[1] > end[1]:
        raise errors.validation("from must not be later than to")
    limit, offset = _limit_offset(query)
    now = instants.key(now_ts())  # the read instant N (D-43)
    snap = {"user": user["id"], "start": start[1] if start else instants.NEG_INF,
            "end": end[1] if end else now,
            "known": min(known[1], now) if known else now,  # nothing is recorded after N yet
            "known_echo": known[0] if known else None, "state": state}
    token = secrets.token_urlsafe(24)
    STORE.snapshots[token] = snap
    return 200, _page(snap, token, limit, offset)
