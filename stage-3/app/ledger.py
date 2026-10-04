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
