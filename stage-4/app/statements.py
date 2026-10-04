"""GET /statement and its snapshots (stage 3; D-48, D-49, D-50, D-54).

A first read freezes a *recipe* — (user, from, resolved to, K' = min(known_at, N), the known_at
echo, and the ledger state object it read) — and returns a page of its result. A snapshot read
recomputes from the recipe. That reproduces the first result exactly: payments and revisions are
append-only and never edited in place, every later write is recorded after N, so selection at
K' <= N sees the same revisions. O(1) memory per snapshot; not exported; only reset ends them
(D-50, final L8). An import swaps in a new state object; recipes keep the one they read.
"""
import hashlib
import json
import secrets

from . import errors, instants, validation
from .ledger import selected, signed
from .payments import page
from .routes import route
from .store import STORE, now_ts, payment_view

WINDOW_PARAMS = ("from", "to", "known_at")
CHUNK = 256  # payment records per interned index chunk of a retained generation (F10)


def _owner_records(state: dict, uid: str):
    """A user's payment records in index order — from a live state, or from a retained
    generation view, whose index is a tuple of shared chunks of records."""
    if "owners" in state:
        for chunk in state["owners"].get(uid, ()):
            yield from chunk
    else:
        for pid in state["user_payments"].get(uid, ()):
            yield state["payments"][pid]


def _compute(state: dict, uid: str, start, end, known) -> dict:
    """D-48 step 4 over [start, end) as known at `known` (keys; start may be -inf)."""
    opening = state["users"][uid]["opening"]
    window = []
    for p in _owner_records(state, uid):
        pid = p["id"]
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


def _render(state: dict, snap: dict, token: str, limit: int, offset: int,
            payments: dict = None) -> dict:
    rows = snap["entries"][offset:offset + limit]
    payments = state["payments"] if payments is None else payments
    entries = []
    for pid, revision, delta, balance_after in rows:
        p = payments[pid]
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
    payments = None
    if "owners" in state:  # a retained generation: look records up by id for this owner
        payments = {p["id"]: p for p in _owner_records(state, snap["user"])}
    return _render(state, result, token, limit, offset, payments)


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
# A retained generation (an older state that recipes still read after an import, L12) is held
# and exported as a view: {currency, users: {uid: {handle, opening}}, owners: {uid: (chunk, ...)}}
# where each chunk is a tuple of up to CHUNK payment records. Records and chunks are interned by
# content digest and whole views deduplicated, so generations that share history share storage:
# a generation that adds k payments costs O(k + CHUNK), in memory and in the export (F9, F10).

def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def _intern_record(record: dict, digest: str = None) -> dict:
    digest = digest or _digest(record)
    shared = STORE.interned.setdefault(digest, record)
    STORE.record_digest[id(shared)] = digest
    return shared


def _intern_chunk(records: list) -> tuple:
    digests = [STORE.record_digest[id(r)] for r in records]
    key = _digest(digests)
    chunk = STORE.chunks.get(key)
    if chunk is None:
        chunk = STORE.chunks[key] = tuple(records)
        STORE.chunk_digest[id(chunk)] = key
    return chunk


def _make_view(currency: str, users: dict, owner_records: dict) -> dict:
    """The shared view for this content (caller holds the lock)."""
    owners = {uid: tuple(_intern_chunk(recs[i:i + CHUNK]) for i in range(0, len(recs), CHUNK))
              for uid, recs in owner_records.items()}
    key = _digest({"currency": currency, "users": users,
                   "owners": {u: [STORE.chunk_digest[id(c)] for c in cs]
                              for u, cs in owners.items()}})
    return STORE.views.setdefault(key, {"currency": currency, "users": users, "owners": owners})


def _view_of(state: dict, uids) -> dict:
    """What recipes of `uids` can read from a state: their payment records, the openings and
    handles involved, the currency — as a shared view."""
    owner_records = {uid: [_intern_record(p) for p in _owner_records(state, uid)] for uid in uids}
    parties = set(uids) | {x for recs in owner_records.values() for p in recs
                           for x in (p["from"], p["to"])}
    users = {u: {"handle": state["users"][u]["handle"], "opening": state["users"][u]["opening"]}
             for u in sorted(parties)}
    return _make_view(state["currency"], users, owner_records)


def retain_generation(old: dict) -> None:
    """Called in the import's swap hold: recipes that read the outgoing state now read its shared
    view, so the rest of the replaced state can be freed."""
    owners = sorted({snap["user"] for snap in STORE.snapshots.values() if snap["state"] is old})
    if not owners:
        return
    view = _view_of(old, owners)
    for snap in STORE.snapshots.values():
        if snap["state"] is old:
            snap["state"] = view


def export_snapshots(current: dict) -> dict:
    """Every live token as a recipe; each distinct retained generation once, as chunk digests
    into one table of distinct chunks and one table of distinct payment records."""
    tokens, generations, index, records, chunks = {}, {}, {}, {}, {}
    for token, snap in STORE.snapshots.items():
        rec = {"user": snap["user"], "start": str(snap["start"]), "end": str(snap["end"]),
               "known": str(snap["known"]), "known_echo": snap["known_echo"]}
        state = snap["state"]
        if state is not current:
            if "owners" not in state:  # not yet retained (defensive): view it now
                state = snap["state"] = _view_of(state, [snap["user"]])
            g = index.get(id(state))
            if g is None:
                g = index[id(state)] = str(len(index))
                for uid, cs in state["owners"].items():
                    for c in cs:
                        cd = STORE.chunk_digest[id(c)]
                        if cd not in chunks:
                            chunks[cd] = [STORE.record_digest[id(r)] for r in c]
                            for r in c:
                                records.setdefault(STORE.record_digest[id(r)], r)
                generations[g] = {"currency": state["currency"], "users": state["users"],
                                  "owners": {u: [STORE.chunk_digest[id(c)] for c in cs]
                                             for u, cs in state["owners"].items()}}
            rec["generation"] = g
        tokens[token] = rec
    return {"tokens": tokens, "generations": generations, "chunks": chunks, "records": records}


def _instant_key(text):
    from decimal import Decimal, InvalidOperation
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return None if value.is_nan() else value


def _check_record(record, bad) -> None:
    revs = record.get("revisions") if isinstance(record, dict) else None
    if not isinstance(revs, list) or not revs or not isinstance(record.get("id"), str) \
            or not all(isinstance(r, dict) and isinstance(r.get("amount"), int)
                       and isinstance(r.get("recorded_at"), str)
                       and isinstance(r.get("effective_at"), str) for r in revs):
        bad("records are malformed")


def _check_generation(view, chunks: dict, records: dict, bad) -> None:
    if not isinstance(view, dict) or not isinstance(view.get("currency"), str):
        bad("generation needs a currency")
    users, owners = view.get("users"), view.get("owners")
    if not isinstance(users, dict) or not isinstance(owners, dict):
        bad("generation needs users and owners")
    for u in users.values():
        if not isinstance(u, dict) or not isinstance(u.get("handle"), str) \
                or not isinstance(u.get("opening"), int) or isinstance(u.get("opening"), bool):
            bad("generation users need a handle and an opening")
    for uid, cds in owners.items():
        if uid not in users or not isinstance(cds, list):
            bad("generation owners are malformed")
        for cd in cds:
            if not isinstance(cd, str) or not isinstance(chunks.get(cd), list):
                bad("generation owners must name chunks")
            for rd in chunks[cd]:
                record = records.get(rd) if isinstance(rd, str) else None
                if record is None:
                    bad("chunks must name records")
                _check_record(record, bad)
                if record.get("from") not in users or record.get("to") not in users:
                    bad("records must name users of their generation")


def import_snapshots(data, state: dict) -> dict:
    """Validated token -> recipe for a stage-4 export's snapshots; raises 422 if malformed.
    Recipes of retained generations carry the generation's raw data until share_imported()
    builds the shared views inside the swap hold."""
    def bad(why):
        raise errors.validation("state: snapshots " + why)
    if not isinstance(data, dict) or not all(
            isinstance(data.get(k), dict) for k in ("tokens", "generations", "chunks", "records")):
        bad("must hold tokens, generations, chunks and records")
    chunks, records = data["chunks"], data["records"]
    for g, view in data["generations"].items():
        _check_generation(view, chunks, records, bad)
    out = {}
    for token, rec in data["tokens"].items():
        if not isinstance(rec, dict):
            bad("tokens must be objects")
        if "generation" in rec:
            view = data["generations"].get(rec["generation"])
            if view is None or rec.get("user") not in view["users"]:
                bad("name unknown users or generations")
            source = {"import": (view, chunks, records)}
        else:
            if rec.get("user") not in state["users"]:
                bad("name unknown users")
            source = state
        keys = [_instant_key(rec.get(k)) for k in ("start", "end", "known")]
        echo = rec.get("known_echo")
        if any(k is None for k in keys) or (echo is not None and not isinstance(echo, str)):
            bad("have an invalid recipe")
        out[token] = {"user": rec["user"], "start": keys[0], "end": keys[1], "known": keys[2],
                      "known_echo": echo, "state": source}
    return out


def share_imported(snapshots: dict, new: dict) -> None:
    """Build the shared views of imported generations (caller holds the swap lock)."""
    built = {}
    for snap in snapshots.values():
        source = snap["state"]
        if source is new:
            continue
        view, chunks, records = source["import"]
        if id(view) not in built:
            owner_records = {
                uid: [_intern_record(records[rd], rd) for cd in cds for rd in chunks[cd]]
                for uid, cds in view["owners"].items()}
            built[id(view)] = _make_view(view["currency"], view["users"], owner_records)
        snap["state"] = built[id(view)]
