"""Payment authorizations (stage 2): authorize, list, capture, void.

Every handler runs inside STORE.hold(), so open holds past their expires_at are already expired
when a handler looks at them. Holds and balances change only through store.py.
"""
from . import validation
from .payments import page, resolve_counterparty
from .routes import route
from .store import AUTH_STATUSES, newest_first, place_hold, remaining

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
