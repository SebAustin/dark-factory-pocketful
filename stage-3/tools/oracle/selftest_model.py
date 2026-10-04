#!/usr/bin/env python3
"""Hand-computed cases for model.py. Every expected number below was worked out on paper from the
specification text (not from the model). Run: python3 selftest_model.py"""
from datetime import timedelta

from model import NEG, POS, Model, parse

T = lambda hms: parse(f"2026-09-24T{hms}+00:00")  # noqa: E731
NOW = T("12:00:00")


def base():
    m = Model({"a": 1000, "b": 0})
    m.add_payment("p1", "a", "b", 300, T("10:00:00"))
    m.add_payment("p2", "b", "a", 100, T("10:05:00"))
    m.add_payment("p3", "a", "b", 50, T("10:05:00"))
    return m


def eq(got, want, what):
    assert got == want, f"{what}: got {got!r}, want {want!r}"


def test_as_of_inclusive():
    m = base()
    eq(m.me("a", T("10:00:00"), None, NOW)["balance"], 700, "payment at exactly as_of counts")
    eq(m.me("a", T("09:59:59"), None, NOW)["balance"], 1000, "before everything = opening")
    eq(m.me("a", T("10:05:00"), None, NOW)["balance"], 750, "both same-instant payments count")
    eq(m.me("a", parse("2100-01-01T00:00:00+00:00"), None, NOW)["balance"], 750, "future as_of = current")
    eq(m.me("b", None, None, NOW)["balance"], 250, "current balance of the other side")


def test_statement_window_and_order():
    m = base()
    s = m.statement("a", T("10:05:00"), T("11:00:00"), None, NOW)
    eq((s["opening_balance"], s["closing_balance"]), (700, 750), "window [10:05, 11:00)")
    eq([(e["id"], e["delta"], e["balance_after"]) for e in s["entries"]], [("p2", 100, 800), ("p3", -50, 750)], "same-instant ties by id")
    s = m.statement("a", T("10:00:00"), T("10:05:00"), None, NOW)
    eq((s["opening_balance"], s["closing_balance"]), (1000, 700), "to is exclusive")
    eq([e["id"] for e in s["entries"]], ["p1"], "only p1 in [10:00, 10:05)")
    s = m.statement("a", None, None, None, NOW)
    eq((s["opening_balance"], s["closing_balance"]), (1000, 750), "default window: opening to now")


def corrected():
    m = base()
    m.add_revision("p1", 2, 100, T("09:00:00"), T("10:10:00"), "fix")
    return m


def test_known_at_selection():
    m = corrected()
    eq(m.me("a", T("09:30:00"), T("10:10:00"), NOW)["balance"], 900, "rev 2 known: moves at its effective time")
    eq(m.me("a", T("09:30:00"), T("10:09:59"), NOW)["balance"], 1000, "rev 2 not yet recorded: rev 1 applies at 10:00")
    eq(m.me("a", T("10:00:00"), T("10:09:59"), NOW)["balance"], 700, "rev 1 effective at 10:00")
    eq(m.me("a", None, None, NOW)["balance"], 950, "current corrected value")
    eq(m.me("a", None, T("09:59:00"), NOW)["balance"], 1000, "nothing recorded yet contributes nothing")
    eq(m.me("a", None, T("10:10:00"), NOW)["balance"], 950, "known_at is inclusive")


def test_statement_corrected_order_and_replacement():
    m = corrected()
    s = m.statement("a", None, None, None, NOW)
    eq([(e["id"], e["revision"], e["amount"], e["delta"], e["balance_after"]) for e in s["entries"]],
       [("p1", 2, 100, -100, 900), ("p2", 1, 100, 100, 1000), ("p3", 1, 50, -50, 950)], "ordered by effective time; replaced revision not counted twice")
    s = m.statement("a", None, None, T("10:09:59"), NOW)
    eq([(e["id"], e["revision"]) for e in s["entries"]], [("p1", 1), ("p2", 1), ("p3", 1)], "known_at before the correction")
    eq(s["closing_balance"], 750, "closing under the old view")
    s = m.statement("a", T("09:30:00"), T("10:05:00"), None, NOW)
    eq((s["opening_balance"], [e["id"] for e in s["entries"]], s["closing_balance"]), (900, [], 900), "a correction moved p1 out of this window")


def test_zero_revision_is_an_entry():
    m = base()
    m.add_revision("p1", 2, 0, T("10:00:00"), T("10:20:00"), "reverse")
    s = m.statement("a", None, None, None, NOW)
    eq([(e["id"], e["delta"]) for e in s["entries"]][0], ("p1", 0), "zero amount still an entry with delta 0")


def holds():
    m = base()
    m.add_auth("h1", "a", "b", 400, T("10:20:00"), T("10:30:00"))
    m.add_payment("c1", "a", "b", 150, T("10:22:00"), kind="capture")
    m.add_capture("h1", "c1")
    m.close_auth("h1", "voided", T("10:25:00"))
    return m


def test_historical_holds():
    m = holds()
    eq(m.me("a", T("10:19:59"), None, NOW)["held"], 0, "not created yet")
    eq(m.me("a", T("10:20:00"), None, NOW)["held"], 400, "hold starts at creation")
    eq(m.me("a", T("10:22:00"), None, NOW)["held"], 250, "nonfinal capture reduces at capture time")
    eq(m.me("a", T("10:25:00"), None, NOW)["held"], 0, "void releases the remainder at its time")
    v = m.me("a", T("10:21:00"), None, NOW)
    eq((v["total"], v["available"], v["balance"]), (750, 350, 750), "available = total - held in one view")
    eq(m.me("a", T("10:26:00"), T("10:24:00"), NOW)["held"], 250, "void not yet known: held until the deadline")
    eq(m.me("a", T("10:30:00"), T("10:24:00"), NOW)["held"], 0, "expiry deadline is known once creation is known")
    eq(m.me("a", T("10:21:00"), T("10:19:00"), NOW)["held"], 0, "creation not known yet")
    eq(m.me("a", T("10:26:00"), None, NOW)["total"], 600, "capture payment moved 150")


def test_expiry_and_final_capture():
    m = base()
    m.add_auth("h2", "a", "b", 100, T("10:40:00"), T("10:50:00"))
    eq(m.me("a", T("10:49:59"), None, NOW)["held"], 100, "open until expires_at")
    eq(m.me("a", T("10:50:00"), None, NOW)["held"], 0, "expiry takes effect at expires_at")
    eq(m.me("a", parse("2100-01-01T00:00:00+00:00"), None, NOW)["held"], 0, "future query: an open hold expires at its deadline")
    m.add_payment("c2", "a", "b", 30, T("10:45:00"), kind="capture")
    m.add_capture("h2", "c2")
    m.close_auth("h2", "captured", T("10:45:00"))
    eq(m.me("a", T("10:45:00"), None, NOW)["held"], 0, "final capture releases the remainder")


def test_correction_outcomes():
    m = base()
    m.add_payment("c1", "a", "b", 150, T("10:22:00"), kind="capture")
    eq(m.correction_outcomes("p1", "a", 1, 100, T("09:00:00"), NOW), {"ok"}, "valid decrease")
    eq(m.correction_outcomes("p1", "b", 1, 100, T("09:00:00"), NOW), {"403"}, "only the sender")
    eq(m.correction_outcomes("zz", "a", 1, 100, T("09:00:00"), NOW), {"404"}, "unknown payment")
    eq(m.correction_outcomes("c1", "a", 1, 10, T("10:22:00"), NOW), {"linked_payment_immutable"}, "captures are immutable")
    eq(m.correction_outcomes("p1", "a", 2, 100, T("09:00:00"), NOW), {"stale_revision"}, "stale expected revision")
    # b's balances: +300 at 10:00, -100 +50 at 10:05, +150 at 10:22. Reversing p1 makes b negative at 10:05.
    eq(m.correction_outcomes("p1", "a", 1, 0, T("10:00:00"), NOW), {"historical_overdraft"}, "b would be at -50 at 10:05")
    eq(m.correction_outcomes("p1", "a", 1, 5000, T("10:00:00"), NOW), {"insufficient_funds"}, "a cannot fund +4700 now")
    eq(m.correction_outcomes("p1", "a", 1, 250, T("10:03:00"), NOW), {"ok"}, "moving p1 later but keeping balances nonnegative")


def test_combined_instant_boundary():
    # a pays b 100 and b pays a 100 at the same instant: the combined effect is zero, never negative.
    m = Model({"a": 0, "b": 0})
    m.add_payment("x1", "a", "b", 100, T("10:00:00"))
    m.add_payment("x2", "b", "a", 100, T("10:00:00"))
    # seeded history must be consistent; the combined-instant rule is what the correction check relies on
    eq(m._would_overdraw(m.payments["x1"], 100, T("10:00:00"), NOW), False, "combined movements at one instant")


def test_instant_grammar():
    from model import parse, parse_query
    eq(parse("2026-09-24T13:20:00+02:00"), parse("2026-09-24t11:20:00Z"), "offsets and T/t/Z/z compare as instants")
    eq(parse("2026-09-24T11:20:00.5Z"), parse("2026-09-24T11:20:00.500000+00:00"), "fraction digits")
    eq(parse("2026-09-24T11:20:00.123456789Z").microsecond, 123456, "nine digits accepted")
    for bad in ("2026-09-24T11:20:00", "2026-09-24", "", "2026-09-24 11:20:00Z", "2026-09-24T11:20:60Z", "2026-09-24T11:20:00+24:00",
                "2026-09-24T11:20:00.1234567890Z", "2026-02-30T00:00:00Z", "2026-09-24T11:20:00 +00:00", "1700000000"):
        try:
            parse(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} must be invalid")
    eq(parse_query("2026-09-24T11:20:00 00:00"), parse("2026-09-24T11:20:00+00:00"), "decoded plus is repaired in queries only")


def test_correction_order_follows_d46():
    m = base()
    m.add_payment("c1", "a", "b", 150, T("10:22:00"), kind="capture")
    # linked beats stale; stale beats insufficient funds and overdraft
    eq(m.correction_result("c1", "a", 9, 10, T("10:22:00"), NOW), "linked_payment_immutable", "linked before stale")
    eq(m.correction_result("p1", "a", 9, 99999, T("10:00:00"), NOW), "stale_revision", "stale before insufficient_funds")
    eq(m.correction_result("p1", "a", 1, 99999, T("10:00:00"), NOW), "insufficient_funds", "funds before overdraft")
    eq(m.correction_result("p1", "b", 9, 0, T("10:00:00"), NOW), "403", "403 before stale")
    eq(m.correction_result("p1", "a", 1, 300, T("10:00:00"), NOW), "ok", "delta 0 is allowed")


def test_import_d52():
    """D-52 by hand: a stage-2 export. a: balance 700; sent p1 (300) and received nothing -> opening 1000. b: balance 300,
    received p1 and a 100 capture c1 and sent 100 (p2) -> opening 300 - 300 - 100 + 100 = 0."""
    state = {"users": {"a": {"balance": 600}, "b": {"balance": 300, "held": 0}},
             "payments": {"p1": {"from": "a", "to": "b", "amount": 300, "created_at": "2026-09-24T10:00:00+00:00", "visibility": "public"},
                          "p2": {"from": "b", "to": "a", "amount": 100, "created_at": "2026-09-24T10:05:00+00:00", "visibility": "public"},
                          "c1": {"from": "a", "to": "b", "amount": 100, "created_at": "2026-09-24T10:22:00+00:00", "visibility": "public",
                                 "authorization_id": "h1"},
                          "s1": {"from": "a", "to": "b", "amount": 0, "created_at": "2026-09-24T10:30:00+00:00", "settlement_id": "st1"}},
             "authorizations": {"h1": {"from": "a", "to": "b", "amount": 400, "status": "voided", "created_at": "2026-09-24T10:20:00+00:00",
                                       "expires_at": "2026-09-24T10:40:00+00:00", "payment_ids": ["c1"]},
                                "h2": {"from": "b", "to": "a", "amount": 50, "status": "voided", "created_at": "2026-09-24T10:10:00+00:00",
                                       "expires_at": "2026-09-24T10:40:00+00:00", "payment_ids": []}}}
    m = Model.from_import(state)
    eq(m.opening, {"a": 600 + 300 - 100 + 100 - 0, "b": 300 - 300 + 100 - 100}, "openings = balance - net of all imported payments")
    eq((m.payments["c1"].kind, m.payments["s1"].kind, m.payments["p1"].kind), ("capture", "settlement", "plain"), "link kinds")
    eq(m.auths["h1"].close, ("voided", T("10:22:00")), "voided stage-2 hold closes at its last capture (D-52)")
    eq(m.auths["h2"].close, ("voided", T("10:10:00")), "voided without captures closes at created_at (D-52)")
    eq(m.me("a", T("10:21:00"), None, NOW)["held"], 400, "h1 holds its full amount until the capture at 10:22")
    eq(m.me("a", T("10:22:00"), None, NOW)["held"], 0, "closing capture releases the rest")
    eq(m.me("b", T("10:10:00"), None, NOW)["held"], 0, "h2 closed at its creation holds nothing")
    eq(m.correction_result("c1", "a", 1, 10, T("10:22:00"), NOW), "linked_payment_immutable", "imported capture is immutable")
    eq(m.correction_result("s1", "a", 1, 10, T("10:30:00"), NOW), "linked_payment_immutable", "imported settlement member is immutable")


def test_sum_of_totals_is_conserved():
    m = corrected()
    m.add_payment("p4", "b", "a", 20, T("11:00:00"))
    for as_of in (NEG, T("09:00:00"), T("10:00:00"), T("10:05:00"), T("11:00:00"), POS):
        for known in (None, T("09:00:00"), T("10:09:59"), T("10:10:00")):
            eq(sum(m.total(u, as_of, known) for u in ("a", "b")), 1000, f"sum of totals as_of={as_of} known={known}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} model cases ok")
