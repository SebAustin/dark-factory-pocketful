"""Payment requests (spec §8 requests endpoints, §4 requests)."""
from . import errors, validation
from .payments import newest_first, page, resolve_counterparty
from .routes import route
from .store import (REQUEST_STATUSES, apply_transfer, new_id, next_seq, now_ts, payment_view,
                    request_view)


def create_request(state: dict, requester_id: str, payer_id: str, amount: int, note: str,
                   ts: str = None) -> dict:
    """Store a new pending request and return its record. Caller holds the lock.

    The payer's balance is not checked: a request may exceed it (spec §4). Callers validate
    amount (splits may pass 0), note and the two parties before calling.
    """
    request = {
        "id": new_id(state, "rq"), "requester": requester_id, "payer": payer_id,
        "amount": amount, "note": note, "status": "pending", "payment_id": None,
        "created_at": ts or now_ts(), "seq": next_seq(state),
    }
    state["requests"][request["id"]] = request
    return request


DIRECTIONS = ("incoming", "outgoing")


def _find(state: dict, request_id: str) -> dict:
    request = state["requests"].get(request_id)
    if request is None:
        raise errors.not_found("no such request")
    return request


def _only(user: dict, party_id: str) -> None:
    if user["id"] != party_id:
        raise errors.forbidden("not permitted on this request")


def _close(state: dict, user: dict, request_id: str, party: str, final: str):
    """Decline (payer) or cancel (requester): repeating the same close is 200, others 409."""
    request = _find(state, request_id)
    _only(user, request[party])
    if request["status"] == "pending":
        request["status"] = final
    elif request["status"] != final:
        raise errors.conflict("request_not_pending", "request is " + request["status"])
    return 200, request_view(state, request)


@route("POST", "/requests", idempotent=True)
def create(ctx, state, user):
    body = ctx.json_object()
    validation.req_str(body, "payer_handle")
    amount = validation.amount(body.get("amount"))
    note = validation.note(body)
    payer = resolve_counterparty(state, user, "payer_handle", body, "self_request")
    return 201, request_view(state, create_request(state, user["id"], payer["id"], amount, note))


@route("POST", "/requests/{request_id}/pay", idempotent=True)
def pay(ctx, state, user):
    visibility = validation.visibility(ctx.json_object())
    request = _find(state, ctx.params["request_id"])
    _only(user, request["payer"])
    if request["status"] != "pending":
        raise errors.conflict("request_not_pending", "request is " + request["status"])
    # Transfer and status change happen in this one lock hold: money moves at most once.
    payment = apply_transfer(state, request["payer"], request["requester"], request["amount"],
                             request["note"], visibility, request_id=request["id"])
    request["status"] = "paid"
    request["payment_id"] = payment["id"]
    return 201, payment_view(state, payment)


@route("POST", "/requests/{request_id}/decline")
def decline(ctx, state, user):
    ctx.json_object(empty_ok=True)
    return _close(state, user, ctx.params["request_id"], "payer", "declined")


@route("POST", "/requests/{request_id}/cancel")
def cancel(ctx, state, user):
    ctx.json_object(empty_ok=True)
    return _close(state, user, ctx.params["request_id"], "requester", "cancelled")


@route("GET", "/requests")
def list_requests(ctx, state, user):
    direction = validation.query_enum(ctx.query, "direction", DIRECTIONS)
    status = validation.query_enum(ctx.query, "status", REQUEST_STATUSES)
    uid = user["id"]
    mine = [r for r in state["requests"].values()
            if (r["payer"] == uid and direction != "outgoing")
            or (r["requester"] == uid and direction != "incoming")]
    if status:
        mine = [r for r in mine if r["status"] == status]
    items, has_more = page(ctx.query, newest_first(mine))
    return 200, {"requests": [request_view(state, r) for r in items], "has_more": has_more}
