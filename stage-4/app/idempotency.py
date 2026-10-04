"""Idempotency records (spec §7). Called by routes.dispatch while it holds STORE.lock.

state["idem"][user_id]["<METHOD> <path>\\n<key>"] = {"canon": str, "body": dict}
Only successful (201) responses are recorded; a 4xx leaves the key free.
"""
from . import errors
from .validation import canonical


def slot(method: str, path: str, key: str) -> str:
    return "{} {}\n{}".format(method, path, key)


def resolve(state: dict, user_id: str, slot_: str, canon: str):
    """Return (200, original body) for a replay, raise 409 for a different body, else None."""
    record = state["idem"].get(user_id, {}).get(slot_)
    if record is None:
        return None
    if record["canon"] != canon:
        raise errors.conflict("idempotency_key_reuse",
                              "key already used with a different request body")
    return 200, record["body"]


def record(state: dict, user_id: str, slot_: str, canon: str, response: dict) -> None:
    """Store a 201 response; `canon` was computed before the handler wrote anything."""
    state["idem"].setdefault(user_id, {})[slot_] = {"canon": canon, "body": response}
