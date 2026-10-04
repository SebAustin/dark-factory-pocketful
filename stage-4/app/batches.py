"""POST /correction-batches (stage 4; D-66..D-70): an operator corrects several payments at once.

prepare() validates (shape, item errors in input order, settlement checks by first appearance,
combined current available, combined history) and builds every object the batch will write — the
revisions with one shared recorded_at, their views, the batch record, the 201 body, the next id —
without touching the state. apply() then only assigns and appends those objects, in the same lock
hold. A refusal or any error while preparing therefore changes nothing, and any two writers naming
the same payment revision serialise on the lock (the second sees stale_revision).
"""
from . import errors, instants, ledger, store
from .corrections import boundaries_ok, fields, item_check, revision_view
from .routes import route
from .store import available, now_ts

MAX_ITEMS = 32


def _shape(body: dict) -> list:
    items = body.get("corrections")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise errors.validation("corrections must be an array of 1 to 32 objects")
    seen = set()
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("payment_id"), str):
            raise errors.validation("every correction is an object with a payment_id string")
        if it["payment_id"] in seen:
            raise errors.validation("payment_ids in one batch must be distinct")
        seen.add(it["payment_id"])
    return items


def _items(state: dict, items: list, now) -> list:
    """Item errors in input order; the first erroneous item decides (D-66 step 1)."""
    checked = []
    for it in items:
        f = fields(it, now)
        p = state["payments"].get(it["payment_id"])
        if p is None:
            raise errors.not_found("no such payment: " + it["payment_id"])
        current = item_check(state, p, f, allow_members=True)
        checked.append((p, current, f))
    return checked


def _members(state: dict, settlement_id: str) -> list:
    record = state["settlements"].get(settlement_id) or {}
    ids = record.get("payment_ids")
    if ids is None:  # older states: membership is the payments' settlement_id
        ids = [pid for pid in state["payment_order"]
               if state["payments"][pid].get("settlement_id") == settlement_id]
    return ids


def _settlements(state: dict, checked: list) -> None:
    """Per settlement, in order of its first member's appearance: complete, then one instant."""
    by_id = {p["id"]: f for p, _, f in checked}
    order = []
    for p, _, _ in checked:
        sid = p.get("settlement_id")
        if sid and sid not in order:
            order.append(sid)
    for sid in order:
        members = _members(state, sid)
        if any(m not in by_id for m in members):
            raise errors.unprocessable("incomplete_settlement",
                                       "every member of settlement {} must be corrected".format(sid))
        if len({instants.key(by_id[m][2]) for m in members}) != 1:
            raise errors.validation("members of one settlement need one effective instant")


def prepare(state: dict, operator: dict, body: dict, now) -> dict:
    """Validate and build everything the batch will write — revisions, views, the batch record,
    the 201 body, the new counter value — without changing the state (plan §3, lead note)."""
    checked = _items(state, _shape(body), now)
    _settlements(state, checked)
    net: dict = {}  # combined current change per wallet (D-67)
    proposed = {}
    for p, current, (_, amount, effective_at, reason) in checked:
        diff = amount - current["amount"]
        net[p["from"]] = net.get(p["from"], 0) - diff
        net[p["to"]] = net.get(p["to"], 0) + diff
        proposed[p["id"]] = {"revision": current["revision"] + 1, "amount": amount,
                             "effective_at": effective_at, "reason": reason}
    if any(available(state["users"][uid]) + d < 0 for uid, d in net.items() if d < 0):
        raise errors.conflict("insufficient_funds", "the batch is not affordable now")
    if not all(boundaries_ok(state, uid, proposed, now) for uid in net):
        raise errors.conflict("historical_overdraft",
                              "the corrected history makes a balance negative")
    batch_id, counter = store.peek_id(state, "cb")
    recorded_at = now_ts()  # one tick, later than every earlier recorded_at (D-41)
    appends = []
    for p, _, _ in checked:
        rev = dict(proposed[p["id"]], recorded_at=recorded_at, correction_batch_id=batch_id)
        appends.append((p, rev, revision_view(p, rev)))
    record = {"id": batch_id, "operator": operator["id"], "recorded_at": recorded_at,
              "payment_ids": [p["id"] for p, _, _ in checked]}
    response = {"correction_batch_id": batch_id, "recorded_at": recorded_at,
                "revisions": [view for _, _, view in appends]}
    return {"counter": counter, "appends": appends, "net": net, "record": record,
            "response": response}


def apply(state: dict, plan: dict) -> dict:
    """Only assignments and appends of objects prepared above; nothing here can fail."""
    state["counters"]["cb"] = plan["counter"]
    for p, rev, _ in plan["appends"]:
        p["revisions"].append(rev)
    for uid, d in plan["net"].items():
        state["users"][uid]["balance"] += d
    state["correction_batches"][plan["record"]["id"]] = plan["record"]
    return plan["response"]


@route("POST", "/correction-batches", idempotent=True, operator=True)
def correction_batch(ctx, state, user):
    now = instants.key(now_ts())  # the batch's read instant N
    return 201, apply(state, prepare(state, user, ctx.json_object(), now))
