"""POST /settlements: an operator submits a batch of transfers that commits all or nothing (§11)."""
from . import errors, store, validation
from .routes import route

MAX_TRANSFERS = 32


def _handle(entry: dict, name: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str):
        raise errors.validation(name + " must be a string")
    return validation.handle_value(value)


def _parse_entry(state: dict, entry) -> dict:
    """Validate one transfer: field rules, then self_payment, then unknown handle (D-13)."""
    if not isinstance(entry, dict):
        raise errors.validation("each transfer must be an object")
    src, dst = _handle(entry, "from_handle"), _handle(entry, "to_handle")
    amount = validation.amount(entry.get("amount"))
    note = validation.note(entry)
    visibility = validation.visibility(entry)
    if src == dst:
        raise errors.unprocessable("self_payment", "a transfer needs two different wallets")
    sender, receiver = store.user_by_handle(state, src), store.user_by_handle(state, dst)
    if sender is None or receiver is None:
        raise errors.not_found("no user has that handle")
    return {"from": sender["id"], "to": receiver["id"], "amount": amount, "note": note,
            "visibility": visibility}


def _parse_batch(state: dict, body: dict) -> list:
    transfers = body.get("transfers")
    if not isinstance(transfers, list) or not 1 <= len(transfers) <= MAX_TRANSFERS:
        raise errors.validation("transfers must hold 1 to 32 objects")
    # Entries are scanned in input order; the first erroneous entry decides the error.
    return [_parse_entry(state, entry) for entry in transfers]


@route("POST", "/settlements", auth=True, idempotent=True, operator=True)
def create_settlement(ctx, state, user):
    batch = _parse_batch(state, ctx.json_object())
    settlement_id = store.new_id(state, "st")
    committed_at = store.now_ts()
    # apply_batch checks every wallet's net result before it moves anything.
    payments = store.apply_batch(state, batch, settlement_id, committed_at)
    state["settlements"][settlement_id] = {
        "id": settlement_id, "committed_at": committed_at,
        "payment_ids": [p["id"] for p in payments],
    }
    return 201, {
        "settlement_id": settlement_id,
        "committed_at": committed_at,
        "payments": [store.payment_view(state, p) for p in payments],
    }
