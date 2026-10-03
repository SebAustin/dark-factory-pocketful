"""POST /payments and GET /activity (spec §8, §4 feed contract)."""
from . import errors, validation
from .routes import route
from .store import apply_transfer, payment_view, user_by_handle


def visible_to(payment: dict, user_id: str) -> bool:
    return (payment["visibility"] == "public"
            or payment["from"] == user_id or payment["to"] == user_id)


def resolve_counterparty(state: dict, caller: dict, handle_field: str, body: dict,
                         self_code: str) -> dict:
    """Read a handle field: 400 wrong type, 422 missing/format, 422 self_code, 404 unknown."""
    handle = validation.req_str(body, handle_field)
    validation.handle_value(handle)
    if handle == caller["handle"]:
        raise errors.unprocessable(self_code, "cannot target your own handle")
    other = user_by_handle(state, handle)
    if other is None:
        raise errors.not_found("no user has that handle")
    return other


def page(query: dict, items: list):
    """Shared limit/offset/has_more rule (spec §8 GET /requests)."""
    limit = validation.query_int(query, "limit", 50, 1, 200)
    offset = validation.query_int(query, "offset", 0, 0)
    return items[offset:offset + limit], len(items) > offset + limit


def newest_first(records):
    return sorted(records, key=lambda r: (r["created_at"], r["seq"]), reverse=True)


@route("POST", "/payments", idempotent=True)
def create_payment(ctx, state, user):
    body = ctx.json_object()
    validation.req_str(body, "to_handle")
    amount = validation.amount(body.get("amount"))
    note = validation.note(body)
    visibility = validation.visibility(body)
    to = resolve_counterparty(state, user, "to_handle", body, "self_payment")
    payment = apply_transfer(state, user["id"], to["id"], amount, note, visibility)
    return 201, payment_view(state, payment)


@route("GET", "/activity")
def activity(ctx, state, user):
    visible = [p for p in state["payments"].values() if visible_to(p, user["id"])]
    items, has_more = page(ctx.query, newest_first(visible))
    return 200, {"payments": [payment_view(state, p) for p in items], "has_more": has_more}
