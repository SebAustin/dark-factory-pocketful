import copy
import json
import unittest

from harness import FIXTURE, call, reset

from app.store import STORE


def fixture():
    f = copy.deepcopy(FIXTURE)
    f["settlement_operator_ids"] = ["u_cy"]
    f["users"][2]["balance"] = 50
    return f


def login(email="ada@example.com", password="correct horse"):
    r = call("POST", "/auth/login", {"email": email, "password": password})
    assert r.status == 200, r.raw
    return r.body["token"]


def dump_state():
    with STORE.lock:
        return json.dumps(STORE.state, sort_keys=True)


def total():
    with STORE.lock:
        return sum(u["balance"] for u in STORE.state["users"].values())


def export():
    r = call("GET", "/_test/export")
    assert r.status == 200, r.raw
    return r.body


def pay(token, to, amount, key, **extra):
    return call("POST", "/payments", {"to_handle": to, "amount": amount, **extra}, token=token, key=key)


def settle(token, transfers, key):
    return call("POST", "/settlements", {"transfers": transfers}, token=token, key=key)


class ExportTest(unittest.TestCase):
    def setUp(self):
        reset(fixture())

    def test_envelope(self):
        body = export()
        self.assertEqual(body["track"], "pocketful")
        self.assertEqual(body["format_version"], 1)
        self.assertIsInstance(body["state"], dict)

    def test_needs_no_token_and_is_read_only(self):
        before = dump_state()
        export()
        export()
        self.assertEqual(dump_state(), before)

    def test_later_writes_do_not_change_an_earlier_export(self):
        snap = export()
        frozen = json.dumps(snap, sort_keys=True)
        pay(login(), "bob", 10, "later")
        self.assertEqual(json.dumps(snap, sort_keys=True), frozen)
        self.assertNotEqual(json.dumps(export(), sort_keys=True), frozen)

    def test_export_of_an_empty_service(self):
        reset({"currency": "JPY", "minor_units": 0, "users": []})
        snap = export()
        reset()
        self.assertEqual(call("POST", "/_test/import", snap).status, 204)
        self.assertEqual(total(), 0)


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        self.ada = login()
        self.op = login("cy@example.com")
        self.pay_a = pay(self.ada, "bob", 700, "pay-a", note="lunch", visibility="private")
        self.settle_a = settle(self.op, [{"from_handle": "cy", "to_handle": "bob", "amount": 20}], "set-a")
        self.failed = pay(self.ada, "bob", 10 ** 9, "failed-key")
        self.assertEqual((self.pay_a.status, self.settle_a.status, self.failed.status), (201, 201, 409))
        self.snap = export()
        self.balances = dump_state()

    def restore_into_a_different_state(self):
        reset({"currency": "JPY", "minor_units": 0, "users": [
            {"id": "x", "email": "x@e.com", "password": "password1", "display_name": "X",
             "handle": "x", "balance": 3}]})
        r = call("POST", "/_test/import", self.snap)
        self.assertEqual((r.status, r.raw), (204, ""))

    def test_state_is_restored_exactly(self):
        pay(self.ada, "bob", 5, "after-export")
        self.restore_into_a_different_state()
        self.assertEqual(dump_state(), self.balances)

    def test_balances_and_sum(self):
        self.restore_into_a_different_state()
        me = call("GET", "/me", token=self.ada)
        self.assertEqual((me.body["balance"], me.body["currency"], me.body["minor_units"]), (9300, "EUR", 2))
        self.assertEqual(total(), 12550)

    def test_old_tokens_remain_valid(self):
        self.restore_into_a_different_state()
        self.assertEqual(call("GET", "/me", token=self.ada).status, 200)
        self.assertEqual(call("GET", "/me", token=self.op).status, 200)

    def test_login_with_original_password_works_and_wrong_one_fails(self):
        self.restore_into_a_different_state()
        self.assertTrue(login("bob@example.com"))
        r = call("POST", "/auth/login", {"email": "bob@example.com", "password": "wrong horse!"})
        self.assertEqual(r.status, 401)
        self.assertEqual(call("POST", "/auth/login", {"email": "x@e.com", "password": "password1"}).status, 401)

    def test_replays_return_200_with_the_original_bodies(self):
        self.restore_into_a_different_state()
        again = pay(self.ada, "bob", 700, "pay-a", note="lunch", visibility="private")
        self.assertEqual(again.status, 200)
        self.assertEqual(again.body, self.pay_a.body)
        again = settle(self.op, [{"from_handle": "cy", "to_handle": "bob", "amount": 20}], "set-a")
        self.assertEqual((again.status, again.body), (200, self.settle_a.body))
        self.assertEqual(dump_state(), self.balances)  # nothing moved a second time

    def test_replay_with_a_different_body_is_still_a_conflict(self):
        self.restore_into_a_different_state()
        r = pay(self.ada, "bob", 701, "pay-a", note="lunch", visibility="private")
        self.assertEqual((r.status, r.code), (409, "idempotency_key_reuse"))

    def test_failed_key_is_reusable(self):
        self.restore_into_a_different_state()
        r = pay(self.ada, "bob", 10, "failed-key")
        self.assertEqual(r.status, 201, r.raw)

    def test_operator_permission_is_kept(self):
        self.restore_into_a_different_state()
        r = settle(self.op, [{"from_handle": "cy", "to_handle": "bob", "amount": 5}], "set-b")
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(settle(self.ada, [{"from_handle": "ada", "to_handle": "bob", "amount": 5}], "x").status, 403)

    def test_payment_identity_and_timestamp_are_not_regenerated(self):
        self.restore_into_a_different_state()
        with STORE.lock:
            p = STORE.state["payments"][self.pay_a.body["payment_id"]]
            self.assertEqual(p["created_at"], self.pay_a.body["created_at"])
            for member in self.settle_a.body["payments"]:
                self.assertEqual(STORE.state["payments"][member["payment_id"]]["settlement_id"],
                                 self.settle_a.body["settlement_id"])
            self.assertIn("rq_1", STORE.state["requests"])

    def test_new_ids_do_not_collide_with_imported_ones(self):
        self.restore_into_a_different_state()
        with STORE.lock:
            existing = set(STORE.state["payments"]) | set(STORE.state["settlements"])
        fresh = pay(self.ada, "bob", 1, "new-1").body["payment_id"]
        member = settle(self.op, [{"from_handle": "cy", "to_handle": "bob", "amount": 1}], "new-2").body
        new_ids = {fresh, member["settlement_id"], member["payments"][0]["payment_id"]}
        self.assertEqual(len(new_ids), 3)
        self.assertFalse(new_ids & existing)
        signup = call("POST", "/auth/signup", {"email": "new@example.com", "password": "password1",
                                                "display_name": "N"})
        with STORE.lock:
            self.assertEqual(len(STORE.state["users"]), 4)
        self.assertEqual(signup.status, 201)

    def test_importing_twice_does_not_duplicate(self):
        self.restore_into_a_different_state()
        self.assertEqual(call("POST", "/_test/import", self.snap).status, 204)
        self.assertEqual(dump_state(), self.balances)
        with STORE.lock:
            self.assertEqual(len(STORE.state["payments"]), 1 + 1 + 1)

    def test_import_replaces_rather_than_merges(self):
        reset(fixture())
        call("POST", "/auth/signup", {"email": "zed@example.com", "password": "password1", "display_name": "Z"})
        stale = login()
        self.assertEqual(call("POST", "/_test/import", self.snap).status, 204)
        self.assertEqual(call("POST", "/auth/login", {"email": "zed@example.com", "password": "password1"}).status, 401)
        self.assertEqual(call("GET", "/me", token=stale).status, 401)  # a token minted after the export
        self.assertEqual(dump_state(), self.balances)

    def test_reset_after_import_clears_everything(self):
        self.restore_into_a_different_state()
        reset(fixture())
        self.assertEqual(call("GET", "/me", token=self.ada).status, 401)
        with STORE.lock:
            self.assertEqual(len(STORE.state["payments"]), 1)
            self.assertEqual(STORE.state["idem"], {})
        self.assertEqual(pay(login(), "bob", 700, "pay-a", note="lunch", visibility="private").status, 201)

    def test_export_after_import_is_equal(self):
        self.restore_into_a_different_state()
        self.assertEqual(export(), self.snap)


class InvalidImportTest(unittest.TestCase):
    def setUp(self):
        reset(fixture())
        pay(login(), "bob", 10, "k")
        self.snap = export()
        self.before = dump_state()

    def rejects(self, mutate, status=422, code="validation_failed"):
        body = copy.deepcopy(self.snap)
        mutate(body)
        r = call("POST", "/_test/import", body)
        self.assertEqual((r.status, r.code), (status, code), r.raw)
        self.assertEqual(dump_state(), self.before)

    def test_envelope_problems(self):
        self.rejects(lambda b: b.pop("state"))
        self.rejects(lambda b: b.pop("track"))
        self.rejects(lambda b: b.pop("format_version"))
        self.rejects(lambda b: b.update(track="other"))
        self.rejects(lambda b: b.update(format_version=2))
        self.rejects(lambda b: b.update(format_version="1"))
        self.rejects(lambda b: b.update(format_version=True))
        self.rejects(lambda b: b.update(state={}))
        self.rejects(lambda b: b.update(state="x"))
        self.rejects(lambda b: b.update(state=None))
        self.rejects(lambda b: b.update(state=[]))

    def test_unparseable_or_non_object_body_is_400(self):
        for raw in ("{", "[1]", "null", "7"):
            r = call("POST", "/_test/import", raw=raw)
            self.assertEqual((r.status, r.code), (400, "malformed_request"), raw)
        self.assertEqual(dump_state(), self.before)

    def test_every_missing_state_key(self):
        from app.transfer_io import STAGE2_DEFAULTS
        for key in self.snap["state"]:
            if key in STAGE2_DEFAULTS:  # optional: a stage-1 export lacks them (plan D10)
                continue
            self.rejects(lambda b, key=key: b["state"].pop(key))

    def test_missing_stage2_keys_take_defaults(self):
        body = json.loads(json.dumps(self.snap))
        body["state"].pop("authorizations")
        body["state"].pop("settings")
        r = call("POST", "/_test/import", body)
        self.assertEqual(r.status, 204, r.raw)
        with STORE.lock:
            self.assertEqual(STORE.state["authorizations"], {})
            self.assertEqual(STORE.state["settings"], {"authorization_ttl_seconds": 600})

    def test_wrong_type_for_every_state_key(self):
        for key in self.snap["state"]:
            for wrong in ("x", 5, None, True):
                original = self.snap["state"][key]
                if type(original) is type(wrong):  # a same-typed value can be legitimate
                    continue
                self.rejects(lambda b, key=key, wrong=wrong: b["state"].update({key: wrong}))
            wrong_container = [] if isinstance(self.snap["state"][key], dict) else {}
            self.rejects(lambda b, key=key: b["state"].update({key: wrong_container}))

    def test_currency_and_minor_units(self):
        self.rejects(lambda b: b["state"].update(currency=""))
        for bad in (1, 4, -1, 2.5, "2", True):
            self.rejects(lambda b, bad=bad: b["state"].update(minor_units=bad))

    def test_balances(self):
        for bad in (-1, 1.5, "10", None, True, 2 ** 53 + 1):
            self.rejects(lambda b, bad=bad: b["state"]["users"]["u_ada"].update(balance=bad))

    def test_user_fields(self):
        self.rejects(lambda b: b["state"]["users"]["u_ada"].update(handle="Ada"))
        self.rejects(lambda b: b["state"]["users"]["u_ada"].update(handle="x" * 21))
        self.rejects(lambda b: b["state"]["users"]["u_ada"].pop("password_hash"))
        self.rejects(lambda b: b["state"]["users"]["u_ada"].update(id="u_other"))
        self.rejects(lambda b: b["state"]["users"]["u_ada"].update(email=5))

    def test_duplicate_handles_and_emails(self):
        def dup_handle(b):
            b["state"]["users"]["u_bob"]["handle"] = "ada"
        self.rejects(dup_handle)

        def dup_email(b):
            b["state"]["users"]["u_bob"]["email"] = "ADA@example.com"
        self.rejects(dup_email)

    def test_indexes_must_agree_with_users(self):
        self.rejects(lambda b: b["state"]["handles"].update(ada="u_bob"))
        self.rejects(lambda b: b["state"]["handles"].update(ghost="u_ada"))
        self.rejects(lambda b: b["state"]["emails"].pop("ada@example.com"))

    def test_dangling_user_ids(self):
        self.rejects(lambda b: next(iter(b["state"]["tokens"])) and b["state"]["tokens"].update(t="u_ghost"))
        self.rejects(lambda b: b["state"]["operators"].append("u_ghost"))
        self.rejects(lambda b: next(iter(b["state"]["payments"].values())).update({"from": "u_ghost"}))
        self.rejects(lambda b: next(iter(b["state"]["payments"].values())).update({"to": "u_ghost"}))
        self.rejects(lambda b: next(iter(b["state"]["requests"].values())).update({"payer": "u_ghost"}))
        self.rejects(lambda b: next(iter(b["state"]["requests"].values())).update({"requester": "u_ghost"}))
        self.rejects(lambda b: b["state"]["idem"].update(u_ghost={}))

    def test_payment_fields(self):
        def edit(**kw):
            return lambda b: next(iter(b["state"]["payments"].values())).update(kw)
        for kw in ({"amount": -1}, {"amount": 1.5}, {"amount": "1"}, {"visibility": "friends"},
                   {"note": None}, {"created_at": 5}, {"seq": "1"}, {"id": "p_other"}):
            self.rejects(edit(**kw))

    def test_payment_order_must_list_the_payments(self):
        self.rejects(lambda b: b["state"]["payment_order"].append("p_ghost"))
        self.rejects(lambda b: b["state"]["payment_order"].pop())
        self.rejects(lambda b: b["state"]["payment_order"].append(b["state"]["payment_order"][0]))

    def test_request_fields(self):
        def edit(**kw):
            return lambda b: next(iter(b["state"]["requests"].values())).update(kw)
        for kw in ({"status": "weird"}, {"status": None}, {"amount": -3}, {"amount": 2.5}, {"note": 1},
                   {"payment_id": 5}, {"id": "rq_other"}):
            self.rejects(edit(**kw))

    def test_timestamps_must_be_rfc3339_with_an_offset(self):
        bad = ("yesterday", "", 5, None, "2026-02-30T00:00:00+00:00", "2026-02-10T00:00:00",
               "2026-02-10", "2026-02-10 00:00:00+00:00", "2026-02-10T25:00:00+00:00", "10/02/2026")
        for value in bad:
            self.rejects(lambda b, v=value: next(iter(b["state"]["payments"].values())).update(created_at=v))
            self.rejects(lambda b, v=value: next(iter(b["state"]["requests"].values())).update(created_at=v))
        self.rejects(lambda b: next(iter(b["state"]["users"].values())).update(created_at="soon"))

    def test_other_valid_offsets_and_forms_are_accepted(self):
        for value in ("2026-02-10T08:00:00+02:00", "2026-02-10T06:00:00Z", "2026-02-10T06:00:00.123456-05:30"):
            body = copy.deepcopy(self.snap)
            next(iter(body["state"]["payments"].values())).update(created_at=value)
            self.assertEqual(call("POST", "/_test/import", body).status, 204, value)

    def test_settlement_and_split_timestamps_when_present(self):
        self.rejects(lambda b: b["state"]["settlements"].update(st_x={"id": "st_x", "committed_at": "later"}))
        self.rejects(lambda b: b["state"]["splits"].update(sp_x={"id": "sp_x", "created_at": 7}))

    def test_huge_exponents_are_refused_quickly(self):
        import time
        for number in ("1e999999999", "1E+400", "1e19", "-1e999999999", "1e-999999999", "123456789012345678901234.5"):
            for key, parent in (("seq", None), ("balance", "u_ada")):
                raw = json.dumps(self.snap)
                if parent is None:
                    raw = json.dumps({**self.snap, "state": {**self.snap["state"], "seq": 0}}).replace('"seq": 0', '"seq": ' + number, 1)
                else:
                    ada = self.snap["state"]["users"]["u_ada"]["balance"]
                    raw = raw.replace('"balance": %d' % ada, '"balance": ' + number, 1)
                began = time.monotonic()
                r = call("POST", "/_test/import", raw=raw)
                self.assertLess(time.monotonic() - began, 5, number)
                self.assertEqual((r.status, r.code), (422, "validation_failed"), (key, number, r.raw[:100]))
                self.assertEqual(dump_state(), self.before)

    def test_counters_and_seq(self):
        self.rejects(lambda b: b["state"].update(seq="9"))
        self.rejects(lambda b: b["state"].update(seq=-1))
        self.rejects(lambda b: b["state"].update(seq=0))  # behind stored records
        self.rejects(lambda b: b["state"]["counters"].update(p="1"))
        self.rejects(lambda b: b["state"]["counters"].update(rq=-1))
        self.rejects(lambda b: b["state"]["counters"].pop("st"))
        self.rejects(lambda b: b["state"]["counters"].update(u=1.5))

    def test_idempotency_records(self):
        def record(b):
            return next(iter(next(iter(b["state"]["idem"].values())).values()))
        self.rejects(lambda b: record(b).pop("canon"))
        self.rejects(lambda b: record(b).update(body="x"))
        self.rejects(lambda b: b["state"]["idem"].update(u_ada="x"))

    def test_unknown_extra_keys_are_ignored(self):
        body = copy.deepcopy(self.snap)
        body["extra"] = 1
        body["state"]["extra"] = {"a": 1}
        self.assertEqual(call("POST", "/_test/import", body).status, 204)
        with STORE.lock:
            self.assertNotIn("extra", STORE.state)
        self.assertEqual(dump_state(), self.before)

    def test_integral_decimal_forms_are_accepted(self):
        raw = json.dumps(self.snap)
        ada = self.snap["state"]["users"]["u_ada"]["balance"]
        raw = raw.replace('"balance": %d' % ada, '"balance": %d.0' % ada)
        self.assertEqual(call("POST", "/_test/import", raw=raw).status, 204)
        self.assertEqual(dump_state(), self.before)


class EveryWriteRoundTripTest(unittest.TestCase):
    """Export after each kind of write the service performs; every export must re-import."""

    def roundtrip(self, label):
        snap = export()
        self.assertEqual(call("POST", "/_test/import", snap).status, 204, label)
        self.assertEqual(export(), snap, label)
        self.assertEqual(call("POST", "/_test/import", snap).status, 204, label + " (twice)")

    def test_state_after_every_kind_of_write(self):
        f = fixture()
        f["requests"] += [
            {"id": "rq_p", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "status": "paid", "payment_id": "p_1"},
            {"id": "rq_d", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "status": "declined"},
            {"id": "rq_c", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 5, "status": "cancelled"},
        ]
        f["payments"].append({"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 3,
                              "visibility": "private", "request_id": "rq_ghost"})
        reset(f)
        self.roundtrip("seeded fixture")
        ada, bob, cy = login(), login("bob@example.com"), login("cy@example.com")
        self.roundtrip("after logins")
        self.assertEqual(pay(ada, "bob", 10, "pub").status, 201)
        self.assertEqual(pay(ada, "bob", 10, "priv", visibility="private", note="é ☕").status, 201)
        self.assertEqual(pay(ada, "bob", 10 ** 9, "failed").status, 409)
        self.roundtrip("after payments")
        signup = call("POST", "/auth/signup", {"email": "New.User@Example.com", "password": "password1",
                                                "display_name": "New"})
        self.assertEqual(signup.status, 201)
        self.assertEqual(call("POST", "/auth/signup", {"email": "bad", "password": "password1",
                                                        "display_name": "x"}).status, 422)
        self.roundtrip("after signup")
        req = {}
        for name in ("pending", "toPay", "toDecline", "toCancel"):
            r = call("POST", "/requests", {"payer_handle": "ada", "amount": 7, "note": name}, token=bob, key="rq-" + name)
            self.assertEqual(r.status, 201, r.raw)
            req[name] = r.body["request_id"]
        self.assertEqual(call("POST", "/requests/%s/pay" % req["toPay"], {"visibility": "private"}, token=ada, key="pay1").status, 201)
        self.assertEqual(call("POST", "/requests/%s/decline" % req["toDecline"], token=ada).status, 200)
        self.assertEqual(call("POST", "/requests/%s/cancel" % req["toCancel"], token=bob).status, 200)
        self.assertEqual(call("POST", "/requests", {"payer_handle": "ada", "amount": 0}, token=bob, key="z").status, 422)
        self.roundtrip("requests in every status")
        zero = call("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"], "note": "z"},
                    token=ada, key="split-zero")
        self.assertEqual(zero.status, 201)
        self.assertEqual([q["amount"] for q in zero.body["requests"]], [0, 0])
        self.roundtrip("after a zero-share split")
        paid0 = call("POST", "/requests/%s/pay" % zero.body["requests"][0]["request_id"], {}, token=bob, key="pay-zero")
        self.assertEqual((paid0.status, paid0.body["amount"]), (201, 0), paid0.raw)
        self.roundtrip("after paying a zero request")
        self.assertEqual(call("POST", "/splits", {"amount": 777, "participant_handles": ["ada"]}, token=ada,
                              key="solo").status, 201)
        self.assertEqual(call("POST", "/splits", {"amount": 3000, "participant_handles": ["bob", "cy"]}, token=ada,
                              key="s2").status, 201)
        self.roundtrip("after more splits")
        op = settle(cy, [{"from_handle": "cy", "to_handle": "bob", "amount": 20},
                         {"from_handle": "bob", "to_handle": "ada", "amount": 20, "visibility": "private"}], "set1")
        self.assertEqual(op.status, 201, op.raw)
        self.assertEqual(settle(cy, [{"from_handle": "cy", "to_handle": "bob", "amount": 10 ** 8}], "set-fail").status, 409)
        self.roundtrip("after a settlement")
        self.assertEqual(pay(ada, "bob", 10, "pub").status, 200)  # replay
        self.assertEqual(export(), export())
        self.roundtrip("after replays")


class LargeStateTest(unittest.TestCase):
    def test_state_over_one_mebibyte_round_trips(self):
        reset(fixture())
        token = login()
        for i in range(1500):
            pay(token, "bob", 1, "bulk-%d" % i, note="n" * 150)
        snap = export()
        size = len(json.dumps(snap))
        self.assertGreater(size, 1024 * 1024)
        before = dump_state()
        reset(fixture())
        r = call("POST", "/_test/import", snap)
        self.assertEqual((r.status, r.raw), (204, ""))
        self.assertEqual(dump_state(), before)


if __name__ == "__main__":
    unittest.main()


class HoldsImportTest(unittest.TestCase):
    """Stage 2: an imported state must keep available = total - held >= 0."""

    def snapshot_with_hold(self, amount, expires):
        from datetime import datetime, timedelta, timezone
        reset()
        body = json.loads(json.dumps(call("GET", "/_test/export").body))
        when = (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat()
        body["state"]["authorizations"] = {"a_x": {
            "id": "a_x", "from": "u_cy", "to": "u_ada", "amount": amount, "captured": 0,
            "note": "", "visibility": "public", "status": "open", "expires_at": when,
            "created_at": when, "seq": 999, "payment_ids": []}}
        body["state"]["seq"] = 1000
        return body

    def test_open_holds_above_balance_are_422_and_change_nothing(self):
        body = self.snapshot_with_hold(1, 3600)  # cy has balance 0
        before = call("GET", "/_test/export").body
        r = call("POST", "/_test/import", body)
        self.assertEqual((r.status, r.code), (422, "validation_failed"), r.raw)
        self.assertEqual(call("GET", "/_test/export").body, before)

    def test_expired_hold_above_balance_is_fine(self):
        body = self.snapshot_with_hold(1, -3600)
        self.assertEqual(call("POST", "/_test/import", body).status, 204)
        with STORE.lock:
            self.assertEqual(STORE.state["authorizations"]["a_x"]["status"], "expired")
            self.assertEqual(STORE.state["users"]["u_cy"]["held"], 0)
