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
                        "correction_batch_id": rev.get("correction_batch_id"),
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


# ---------------------------------------------------------------- export / import (L10, L12)

def _ledger_view(state: dict, uids) -> dict:
    """What recipes of `uids` can read from an older state: their payments with revisions, the
    openings and handles involved, and the currency. Exported once per retained state (F9)."""
    payment_ids = []
    for uid in uids:
        payment_ids.extend(state["user_payments"].get(uid, ()))
    payments = {pid: state["payments"][pid] for pid in payment_ids}
    parties = set(uids) | {x for p in payments.values() for x in (p["from"], p["to"])}
    return {"currency": state["currency"],
            "users": {u: {"handle": state["users"][u]["handle"],
                          "opening": state["users"][u]["opening"]} for u in parties},
            "user_payments": {u: list(state["user_payments"].get(u, ())) for u in uids},
            "payments": payments}


def _digest(obj) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _shared(view: dict) -> dict:
    """One object per distinct generation content: payment records interned by content, whole
    views deduplicated (F10). Caller holds the lock."""
    digests = {}
    payments = {}
    for pid, record in view["payments"].items():
        d = _digest(record)
        payments[pid] = STORE.interned.setdefault(d, record)
        digests[pid] = d
    key = _digest({"currency": view["currency"], "users": view["users"],
                   "user_payments": view["user_payments"], "payments": digests})
    return STORE.views.setdefault(key, dict(view, payments=payments))


def retain_generation(old: dict) -> None:
    """Called in the import's swap hold: recipes that read the outgoing state now read one
    shared compact view of it (their owners' payments, openings, handles, currency), so the rest
    of the replaced state can be freed; identical content is shared across imports (F9, F10)."""
    owners = sorted({snap["user"] for snap in STORE.snapshots.values() if snap["state"] is old})
    if not owners:
        return
    view = _shared(_ledger_view(old, owners))
    for snap in STORE.snapshots.values():
        if snap["state"] is old:
            snap["state"] = view


def share_imported(snapshots: dict, new: dict) -> None:
    """Imported generation views join the shared store too (caller holds the lock)."""
    done = {}
    for snap in snapshots.values():
        if snap["state"] is not new:
            key = id(snap["state"])
            if key not in done:
                done[key] = _shared(snap["state"])
            snap["state"] = done[key]


def export_snapshots(current: dict) -> dict:
    """Every live token as a recipe. Recipes reading the exported state need nothing more; each
    distinct older generation is exported once, its payments as digests into one table of
    distinct payment records, so the export grows with distinct ledger content (F9, F10)."""
    tokens, generations, owners, index, records = {}, {}, {}, {}, {}
    for token, snap in STORE.snapshots.items():
        rec = {"user": snap["user"], "start": str(snap["start"]), "end": str(snap["end"]),
               "known": str(snap["known"]), "known_echo": snap["known_echo"]}
        if snap["state"] is not current:
            g = index.setdefault(id(snap["state"]), str(len(index)))
            owners.setdefault(g, (snap["state"], set()))[1].add(snap["user"])
            rec["generation"] = g
        tokens[token] = rec
    for g, (state, uids) in owners.items():
        view = _ledger_view(state, sorted(uids))
        refs = {}
        for pid, record in view["payments"].items():
            d = _digest(record)
            records.setdefault(d, record)
            refs[pid] = d
        generations[g] = dict(view, payments=refs)
    return {"tokens": tokens, "generations": generations, "records": records}


def _instant_key(text):
    from decimal import Decimal, InvalidOperation
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return None if value.is_nan() else value


def _generation(view, records: dict, bad) -> dict:
    """A validated ledger view, usable by _compute and _render like a state."""
    if not isinstance(view, dict) or not isinstance(view.get("currency"), str):
        bad("generation needs a currency")
    users, refs, index = view.get("users"), view.get("payments"), view.get("user_payments")
    if not all(isinstance(x, dict) for x in (users, refs, index)):
        bad("generation needs users, payments and user_payments")
    if any(not isinstance(d, str) or d not in records for d in refs.values()):
        bad("generation payments must name records")
    payments = {pid: records[d] for pid, d in refs.items()}
    for u in users.values():
        if not isinstance(u, dict) or not isinstance(u.get("handle"), str) \
                or not isinstance(u.get("opening"), int) or isinstance(u.get("opening"), bool):
            bad("generation users need a handle and an opening")
    for pid, p in payments.items():
        revs = p.get("revisions") if isinstance(p, dict) else None
        if p is None or p.get("id") != pid or p.get("from") not in users or p.get("to") not in users \
                or not isinstance(revs, list) or not revs \
                or not all(isinstance(r, dict) and isinstance(r.get("amount"), int)
                           and isinstance(r.get("recorded_at"), str)
                           and isinstance(r.get("effective_at"), str) for r in revs):
            bad("generation payments are malformed")
    for uid, pids in index.items():
        if uid not in users or not isinstance(pids, list) or any(q not in payments for q in pids):
            bad("generation user_payments are malformed")
    return {"currency": view["currency"], "users": users, "payments": payments,
            "user_payments": index}


def import_snapshots(data, state: dict) -> dict:
    """Validated token -> recipe for a stage-4 export's snapshots; raises 422 if malformed."""
    def bad(why):
        raise errors.validation("state: snapshots " + why)
    if not isinstance(data, dict) or not all(isinstance(data.get(k), dict)
                                             for k in ("tokens", "generations", "records")):
        bad("must hold tokens, generations and records")
    records = data["records"]
    generations = {g: _generation(v, records, bad) for g, v in data["generations"].items()}
    out = {}
    for token, rec in data["tokens"].items():
        if not isinstance(rec, dict):
            bad("tokens must be objects")
        source = generations.get(rec["generation"]) if "generation" in rec else state
        if source is None or rec.get("user") not in source["users"]:
            bad("name unknown users or generations")
        keys = [_instant_key(rec.get(k)) for k in ("start", "end", "known")]
        echo = rec.get("known_echo")
        if any(k is None for k in keys) or (echo is not None and not isinstance(echo, str)):
            bad("have an invalid recipe")
        out[token] = {"user": rec["user"], "start": keys[0], "end": keys[1], "known": keys[2],
                      "known_echo": echo, "state": source}
    return out
