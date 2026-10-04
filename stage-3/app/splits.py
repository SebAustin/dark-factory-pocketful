"""POST /splits: split an amount the caller paid and ask each other participant for a share (§8, §9)."""
from . import errors, validation
from .requests_ import create_request
from .routes import route
from .store import new_id, now_ts, request_view, user_by_handle


def shares(amount: int, n: int) -> list:
    """Equal split in whole minor units; the first `amount % n` participants get one extra."""
    base, extra = divmod(amount, n)
    return [base + (1 if i < extra else 0) for i in range(n)]


def _handles(body: dict) -> list:
    """participant_handles: wrong JSON type 400, then empty / duplicate / bad format 422."""
    if "participant_handles" not in body:
        raise errors.validation("participant_handles is required")
    handles = body["participant_handles"]
    if not isinstance(handles, list) or any(not isinstance(h, str) for h in handles):
        raise errors.malformed("participant_handles must be an array of strings")
    return handles


def _check_handles(handles: list) -> None:
    if not handles:
        raise errors.validation("participant_handles must not be empty")
    if len(set(handles)) != len(handles):
        raise errors.validation("participant_handles must not repeat a handle")
    for handle in handles:
        validation.handle_value(handle)


@route("POST", "/splits", auth=True, idempotent=True)
def create_split(ctx, state, user):
    body = ctx.json_object()
    handles = _handles(body)
    amount = validation.amount(body.get("amount"))
    note = validation.note(body)
    _check_handles(handles)
    participants = []
    for handle in handles:
        found = user_by_handle(state, handle)
        if found is None:
            raise errors.not_found("no user has that handle")
        participants.append(found)

    ts = now_ts()
    split_id = new_id(state, "sp")
    parts = shares(amount, len(participants))
    created = [create_request(state, user["id"], p["id"], share, note, ts)
               for p, share in zip(participants, parts) if p["id"] != user["id"]]
    state["splits"][split_id] = {
        "id": split_id, "owner": user["id"], "amount": amount, "note": note,
        "shares": [{"user_id": p["id"], "amount": s} for p, s in zip(participants, parts)],
        "request_ids": [r["id"] for r in created], "created_at": ts,
    }
    return 201, {
        "split_id": split_id, "amount": amount, "currency": state["currency"], "note": note,
        "shares": [{"handle": h, "amount": s} for h, s in zip(handles, parts)],
        "requests": [request_view(state, r) for r in created],
        "created_at": ts,
    }
