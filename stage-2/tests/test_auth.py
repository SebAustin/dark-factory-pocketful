import unittest

from harness import call, reset

from app.store import STORE


def signup(email, password="correct horse", display_name="New"):
    return call("POST", "/auth/signup",
                {"email": email, "password": password, "display_name": display_name})


def login(email, password="correct horse"):
    return call("POST", "/auth/login", {"email": email, "password": password})


class SignupTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_signup_201_shape_and_zero_balance(self):
        r = signup("dee@example.com", display_name="Dee")
        self.assertEqual(r.status, 201, r.raw)
        self.assertEqual(set(r.body), {"user_id", "display_name", "token"})
        self.assertEqual(r.body["display_name"], "Dee")
        me = call("GET", "/me", token=r.body["token"])
        self.assertEqual(me.status, 200)
        self.assertEqual(me.body, {"user_id": r.body["user_id"], "display_name": "Dee",
                                   "handle": "dee", "balance": 0, "currency": "EUR",
                                   "minor_units": 2})

    def test_handle_derivation(self):
        cases = {
            "Ada.Lovelace+x@example.com": "ada_lovelace_x",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ@e.com": "abcdefghijklmnopqrst",
            "jürgen-o'neil@e.com": "j_rgen_o_neil",
            "x_9@e.com": "x_9",
        }
        for email, handle in cases.items():
            r = signup(email)
            self.assertEqual(r.status, 201, (email, r.raw))
            me = call("GET", "/me", token=r.body["token"])
            self.assertEqual(me.body["handle"], handle)

    def test_email_taken(self):
        self.assertEqual(signup("ada@example.com").code, "email_taken")
        r = signup("ADA@example.com")
        self.assertEqual((r.status, r.code), (409, "email_taken"))

    def test_handle_taken_creates_no_account(self):
        r = signup("bob@other.org")
        self.assertEqual((r.status, r.code), (409, "handle_taken"))
        self.assertEqual(login("bob@other.org").status, 401)
        with STORE.lock:
            self.assertEqual(len(STORE.state["users"]), 3)

    def test_short_password_422(self):
        r = signup("new@example.com", password="1234567")
        self.assertEqual((r.status, r.code), (422, "validation_failed"))
        self.assertEqual(signup("new@example.com", password="12345678").status, 201)

    def test_bad_email_422(self):
        for email in ("noatsign", "@e.com", "a@", "a@b@c", "a b@c.com", ""):
            r = signup(email)
            self.assertEqual((r.status, r.code), (422, "validation_failed"), email)

    def test_missing_fields_422_wrong_types_400(self):
        r = call("POST", "/auth/signup", {"email": "x@e.com", "password": "correct horse"})
        self.assertEqual(r.status, 422)
        r = call("POST", "/auth/signup", {"email": 5, "password": "correct horse",
                                          "display_name": "X"})
        self.assertEqual((r.status, r.code), (400, "malformed_request"))
        r = call("POST", "/auth/signup", raw="{")
        self.assertEqual((r.status, r.code), (400, "malformed_request"))

    def test_unknown_fields_ignored(self):
        r = call("POST", "/auth/signup", {"email": "z@e.com", "password": "correct horse",
                                          "display_name": "Z", "handle": "zzz", "x": 1})
        self.assertEqual(r.status, 201)
        self.assertEqual(call("GET", "/me", token=r.body["token"]).body["handle"], "z")

    def test_password_not_stored_in_plaintext(self):
        signup("plain@example.com", password="super secret pw")
        with STORE.lock:
            stored = [u["password_hash"] for u in STORE.state["users"].values()]
        self.assertFalse(any("super secret pw" in s for s in stored))


class LoginTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_seeded_user_logs_in(self):
        r = login("ada@example.com")
        self.assertEqual(r.status, 200, r.raw)
        self.assertEqual(r.body["user_id"], "u_ada")
        self.assertEqual(r.body["display_name"], "Ada")
        me = call("GET", "/me", token=r.body["token"])
        self.assertEqual(me.body["balance"], 10000)

    def test_wrong_password_and_unknown_email_401(self):
        self.assertEqual(login("ada@example.com", "wrong horse").code, "unauthenticated")
        self.assertEqual(login("nobody@example.com").status, 401)

    def test_multiple_tokens_all_valid(self):
        t1 = login("ada@example.com").body["token"]
        t2 = login("ada@example.com").body["token"]
        self.assertNotEqual(t1, t2)
        self.assertEqual(call("GET", "/me", token=t1).status, 200)
        self.assertEqual(call("GET", "/me", token=t2).status, 200)

    def test_signed_up_user_logs_in(self):
        signup("eve@example.com", password="eve password")
        r = login("eve@example.com", "eve password")
        self.assertEqual(r.status, 200)


class TokenTest(unittest.TestCase):
    def setUp(self):
        reset()

    def test_missing_malformed_unknown_token_401(self):
        self.assertEqual(call("GET", "/me").code, "unauthenticated")
        self.assertEqual(call("GET", "/me", token="nope").status, 401)
        r = call("GET", "/me", headers={"Authorization": "Basic abc"})
        self.assertEqual(r.status, 401)

    def test_reset_invalidates_tokens(self):
        token = login("ada@example.com").body["token"]
        reset()
        self.assertEqual(call("GET", "/me", token=token).status, 401)


if __name__ == "__main__":
    unittest.main()
