"""Payment authorizations (stage 2): authorize, list, capture, void.

Every handler runs inside STORE.hold(), so open holds past their expires_at are already expired
when a handler looks at them. Holds and balances change only through store.py.
"""
from . import errors, validation
from .payments import page, resolve_counterparty
from .routes import route
from .store import (AUTH_STATUSES, apply_capture, is_expired, newest_first, payment_view,
                    place_hold, remaining, void_authorization)

DIRECTIONS = ("incoming", "outgoing")


def authorization_view(state: dict, a: dict) -> dict:
    users = state["users"]
    ids = a["payment_ids"]
    return {
        "authorization_id": a["id"],
        "from_user_id": a["from"], "from_handle": users[a["from"]]["handle"],
        "to_user_id": a["to"], "to_handle": users[a["to"]]["handle"],
        "amount": a["amount"], "captured_amount": a["captured"],
        "remaining_amount": remaining(a), "currency": state["currency"],
        "note": a["note"], "visibility": a["visibility"], "status": a["status"],
        "expires_at": a["expires_at"], "payment_id": ids[-1] if ids else None,
        "payment_ids": list(ids), "created_at": a["created_at"],
    }


@route("POST", "/authorizations", idempotent=True)
def authorize(ctx, state, user):
    body = ctx.json_object()
    validation.req_str(body, "to_handle")
    amount = validation.amount(body.get("amount"))
    note = validation.note(body)
    visibility = validation.visibility(body)
    to = resolve_counterparty(state, user, "to_handle", body, "self_payment")
    a = place_hold(state, user["id"], to["id"], amount, note, visibility)
    return 201, authorization_view(state, a)


@route("GET", "/authorizations")
def list_authorizations(ctx, state, user):
    direction = validation.query_enum(ctx.query, "direction", DIRECTIONS)
    status = validation.query_enum(ctx.query, "status", AUTH_STATUSES)
    uid = user["id"]
    mine = [a for a in state["authorizations"].values()
            if (a["from"] == uid and direction != "incoming")
            or (a["to"] == uid and direction != "outgoing")]
    if status:
        mine = [a for a in mine if a["status"] == status]
    items, has_more = page(ctx.query, newest_first(mine))
    return 200, {"authorizations": [authorization_view(state, a) for a in items],
                 "has_more": has_more}


def _find(state: dict, authorization_id: str) -> dict:
    a = state["authorizations"].get(authorization_id)
    if a is None:
        raise errors.not_found("no such authorization")
    return a


def _capture_fields(body: dict):
    """(amount or None, final): amount 422 if invalid, final 400 if not a boolean (D12)."""
    amount = None
    if "amount" in body:
        amount = validation.integral(body["amount"])
        if amount is None or amount < 1:
            raise errors.validation("amount must be an integer of at least 1")
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise errors.malformed("final must be a boolean")
    return amount, final


@route("POST", "/authorizations/{authorization_id}/capture", idempotent=True)
def capture(ctx, state, user):
    amount, final = _capture_fields(ctx.json_object())
    a = _find(state, ctx.params["authorization_id"])
    if user["id"] != a["to"]:
        raise errors.forbidden("only the receiver may capture")
    if is_expired(a):  # D8: a clock-expired hold is "expired", not "not open"
        raise errors.conflict("authorization_expired", "the authorization has expired")
    left = remaining(a)
    if a["status"] != "open" or left == 0:  # a seeded open hold may have nothing left
        raise errors.conflict("authorization_not_open", "the authorization is " + a["status"])
    amount = left if amount is None else amount
    if amount > left:
        raise errors.unprocessable("capture_exceeds_authorization",
                                   "amount is above the remaining {}".format(left))
    payment = apply_capture(state, a, amount, final)
    return 201, payment_view(state, payment)


@route("POST", "/authorizations/{authorization_id}/void")
def void(ctx, state, user):
    ctx.json_object(empty_ok=True)
    a = _find(state, ctx.params["authorization_id"])
    if user["id"] != a["from"]:
        raise errors.forbidden("only the payer may void")
    if a["status"] == "open":
        void_authorization(state, a)
    elif a["status"] != "voided":
        raise errors.conflict("authorization_not_open", "the authorization is " + a["status"])
    return 200, authorization_view(state, a)
