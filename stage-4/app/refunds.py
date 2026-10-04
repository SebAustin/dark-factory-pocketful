"""POST /payments/{id}/refunds (stage 4): the receiver sends money back, as a new payment.

Order (plan §1): 422 amount -> 404 -> 403 not the receiver -> 422 invalid_refund_target ->
422 refund_exceeds_payment -> 409 insufficient_funds (receiver's available) -> commit, all in
the pipeline's one lock hold. Refunds never touch requests, holds or settlement membership.
"""
from . import errors, ledger, validation
from .routes import route
from .store import apply_refund, payment_view


@route("POST", "/payments/{payment_id}/refunds", idempotent=True)
def refund(ctx, state, user):
    amount = validation.amount(ctx.json_object().get("amount"))
    target = state["payments"].get(ctx.params["payment_id"])
    if target is None:
        raise errors.not_found("no such payment")
    if user["id"] != target["to"]:
        raise errors.forbidden("only the original receiver may refund a payment")
    if target.get("refund_of"):
        raise errors.unprocessable("invalid_refund_target", "a refund cannot be refunded")
    if ledger.refunded(state, target["id"]) + amount > ledger.latest(target)["amount"]:
        raise errors.unprocessable("refund_exceeds_payment",
                                   "refunds may not exceed the payment's corrected amount")
    return 201, payment_view(state, apply_refund(state, target, amount))
