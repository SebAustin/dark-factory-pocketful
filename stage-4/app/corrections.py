"""Payment corrections and revision history (stage 3; D-46, D-47, D-53, D-56..D-59).

A correction appends an immutable revision to a payment and moves the amount difference between
the same two wallets in the same lock hold. Every check happens before any write, so a refusal
leaves balances, revisions, statements, snapshots and idempotency state untouched.
"""
from . import errors, instants, ledger, validation
from .routes import route
from .store import available, now_ts

MAX_AMOUNT = 1_000_000_000
MAX_REASON = 200


def revision_view(p: dict, rev: dict) -> dict:
    return {"payment_id": p["id"], "revision": rev["revision"], "amount": rev["amount"],
            "effective_at": rev["effective_at"], "recorded_at": rev["recorded_at"],
            "reason": rev["reason"],
            "correction_batch_id": rev.get("correction_batch_id")}  # D-69: null unless a batch


def _fields(body: dict, now):
    """D-46: every field defect, wrong JSON type included, is 422 validation_failed."""
    expected = validation.integral(body.get("expected_revision"))
    if expected is None or expected < 1:
        raise errors.validation("expected_revision must be a positive integer")
    amount = validation.integral(body.get("amount"))
    if amount is None or not 0 <= amount <= MAX_AMOUNT:
        raise errors.validation("amount must be an integer from 0 to 1000000000")
    effective_at = body.get("effective_at")
    when = instants.key(effective_at)
    if when is None or when > now:  # D-58: not later than the read instant, no tolerance
        raise errors.validation("effective_at must be an RFC 3339 instant not later than now")
    reason = body.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason) <= MAX_REASON:
        raise errors.validation("reason must be a string of 1 to 200 characters")
    return expected, amount, effective_at, reason


def _boundaries_ok(state: dict, uid: str, p: dict, new_rev: dict, now) -> bool:
    """D-53: with the new revision selected, total and available stay >= 0 at every past
    boundary (all movements at one instant combined), starting from the opening."""
    changes: dict = {}  # instant key -> [total delta, held delta]

    def add(at, d_total, d_held):
        k = instants.key_or_min(at)
        if k <= now:
            slot = changes.setdefault(k, [0, 0])
            slot[0] += d_total
            slot[1] += d_held

    for pid in state["user_payments"].get(uid, ()):
        q = state["payments"][pid]
        rev = new_rev if pid == p["id"] else ledger.latest(q)
        add(rev["effective_at"], ledger.signed(uid, q, rev["amount"]), 0)
    for a in state["authorizations"].values():
        if a["from"] == uid:
            for e in a.get("events") or ():
                add(e["at"], 0, e["held_delta"])
    total, held = state["users"][uid]["opening"], 0
    if total < 0:
        return False
    for k in sorted(changes):
        total += changes[k][0]
        held += changes[k][1]
        if total < 0 or total - held < 0:
            return False
    return True


@route("POST", "/payments/{payment_id}/corrections", idempotent=True)
def correct(ctx, state, user):
    now = instants.key(now_ts())  # the correction's read instant N
    expected, amount, effective_at, reason = _fields(ctx.json_object(), now)
    p = state["payments"].get(ctx.params["payment_id"])
    if p is None:
        raise errors.not_found("no such payment")
    if user["id"] != p["from"]:
        raise errors.forbidden("only the original sender may correct a payment")
    if p.get("settlement_id") or p.get("authorization_id") or p.get("refund_of"):
        raise errors.unprocessable("linked_payment_immutable",
                                   "settlement members, captures and refunds cannot be corrected")
    current = ledger.latest(p)
    if expected != current["revision"]:
        raise errors.conflict("stale_revision", "the payment is at revision {}".format(
            current["revision"]))
    if amount < ledger.refunded(state, p["id"]):
        raise errors.unprocessable("refund_exceeds_payment",
                                   "the payment has already been refunded beyond that amount")
    diff = amount - current["amount"]
    payer, payee = state["users"][p["from"]], state["users"][p["to"]]
    debited = payer if diff > 0 else payee
    if diff and available(debited) < abs(diff):
        raise errors.conflict("insufficient_funds", "the debited wallet cannot cover the change")
    new_rev = {"revision": current["revision"] + 1, "amount": amount,
               "effective_at": effective_at, "recorded_at": now_ts(), "reason": reason}
    if not all(_boundaries_ok(state, uid, p, new_rev, now) for uid in (p["from"], p["to"])):
        raise errors.conflict("historical_overdraft",
                              "the corrected history makes a balance negative")
    p["revisions"].append(new_rev)
    payer["balance"] -= diff
    payee["balance"] += diff
    return 201, revision_view(p, new_rev)


@route("GET", "/payments/{payment_id}/revisions")
def revisions(ctx, state, user):
    p = state["payments"].get(ctx.params["payment_id"])
    if p is None or user["id"] not in (p["from"], p["to"]):
        raise errors.not_found("no such payment")  # third parties too, even when public
    return 200, {"revisions": [revision_view(p, r) for r in p["revisions"]]}
