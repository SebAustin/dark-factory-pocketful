"""Bitemporal ledger (stage 3; plan §1–§2).

A payment's stage 1 record never changes; its money history is the append-only `revisions`
list. Opening balances and the per-user payment index are derived and rebuilt on reset/import.
Functions take the state dict and expect the caller to hold STORE.hold() unless they build a
fresh state off to the side (reset, import).
"""
from .instants import key_or_min


def revision_one(p: dict) -> dict:
    """Revision 1: the amount as originally paid, effective = recorded = created_at."""
    return {"revision": 1, "amount": p["amount"], "effective_at": p["created_at"],
            "recorded_at": p["created_at"], "reason": ""}


def signed(uid: str, p: dict, amount: int) -> int:
    """The effect of a payment amount on uid's balance (+ received, - sent)."""
    return amount if p["to"] == uid else -amount


def latest(p: dict) -> dict:
    return p["revisions"][-1]


def index_payment(state: dict, p: dict) -> None:
    for uid in (p["from"], p["to"]):
        state["user_payments"].setdefault(uid, []).append(p["id"])


def rebuild_user_payments(state: dict) -> None:
    state["user_payments"] = {uid: [] for uid in state["users"]}
    for pid in state["payment_order"]:
        index_payment(state, state["payments"][pid])


def compute_openings(state: dict) -> None:
    """opening = balance now - net effect of every payment's latest revision."""
    for uid, user in state["users"].items():
        net = sum(signed(uid, state["payments"][pid], latest(state["payments"][pid])["amount"])
                  for pid in state["user_payments"].get(uid, ()))
        user["opening"] = user["balance"] - net


def history_is_nonnegative(state: dict, uid: str) -> bool:
    """Total never below zero at any effective-time boundary (same-instant movements combined)."""
    opening = state["users"][uid]["opening"]
    if opening < 0:
        return False
    deltas: dict = {}
    for pid in state["user_payments"].get(uid, ()):
        p = state["payments"][pid]
        rev = latest(p)
        k = key_or_min(rev["effective_at"])
        deltas[k] = deltas.get(k, 0) + signed(uid, p, rev["amount"])
    running = opening
    for k in sorted(deltas):
        running += deltas[k]
        if running < 0:
            return False
    return True


# ---------------------------------------------------------------- historical views (D-48, D-51)

def selected(p: dict, known):
    """The latest revision recorded at or before `known` (a key), or None (D-48 step 1)."""
    for rev in reversed(p["revisions"]):
        if key_or_min(rev["recorded_at"]) <= known:
            return rev
    return None


def total_at(state: dict, uid: str, at, known) -> int:
    """Balance of uid at instant `at` (inclusive) as known at `known` (D-48)."""
    total = state["users"][uid]["opening"]
    for pid in state["user_payments"].get(uid, ()):
        p = state["payments"][pid]
        rev = selected(p, known)
        if rev is not None and key_or_min(rev["effective_at"]) <= at:
            total += signed(uid, p, rev["amount"])
    return total


def hold_at(a: dict, at, known) -> int:
    """What one hold reserves at `at` as known at `known` (D-51)."""
    events = a.get("events") or []
    if not events or events[0]["kind"] != "created":
        return 0  # seeded closed holds hold nothing at any instant
    created = key_or_min(events[0]["at"])
    if created > known or at < created:
        return 0
    if at >= key_or_min(a["expires_at"]):
        return 0  # expiry is known as soon as creation is known
    held = events[0]["held_delta"]
    for e in events[1:]:
        when = key_or_min(e["at"])
        if when <= known and when <= at:
            held += e["held_delta"]
    return max(held, 0)


def held_at(state: dict, uid: str, at, known) -> int:
    return sum(hold_at(a, at, known) for a in state["authorizations"].values()
               if a["from"] == uid)
