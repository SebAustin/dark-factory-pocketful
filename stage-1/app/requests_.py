"""Payment requests (spec §8 requests endpoints, §4 requests)."""
from .store import new_id, next_seq, now_ts


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
