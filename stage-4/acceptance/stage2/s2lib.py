"""Shared helpers for the stage 2 acceptance suite (API over httpx, screens over playwright).

Black box: everything goes through HTTP at TARGET_URL (and STAGE1_URL for the upgrade tests).
Expected values come from runlog/stage2-spec.md and stage-2/docs/ledger.md; test names carry the
ledger ids (test_R2_CAP_12_... -> R2-CAP.12).
"""
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

TARGET_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:18100").rstrip("/")
STAGE1_URL = os.environ.get("STAGE1_URL", "http://127.0.0.1:18101").rstrip("/")
PASSWORD = "correct horse"
REQUEST_TIMEOUT = 5.0
CONTROL_TIMEOUT = 10.0

RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")

PAYMENT_KEYS = {
    "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
    "currency", "note", "visibility", "request_id", "created_at", "settlement_id",
    "authorization_id",
    # stage 4 (R4-RSH.5, decision D-75): every payment carries refund_of
    "refund_of",
}
AUTH_KEYS = {  # D-32
    "authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
    "captured_amount", "remaining_amount", "currency", "note", "visibility", "status",
    "expires_at", "payment_id", "payment_ids", "created_at",
    # stage 3 (R3-HH.9, decision D-61): authorizations expose closed_at
    "closed_at",
}


def new_key():
    return "k-" + uuid.uuid4().hex


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))


def user(uid, handle, balance, **extra):
    return {"id": uid, "email": f"{handle}@example.com", "password": PASSWORD,
            "display_name": handle.capitalize(), "handle": handle, "balance": balance, **extra}


def auth_rec(aid, frm, to, amount, status="open", expires_at=None, **extra):
    return {"id": aid, "from_user_id": frm, "to_user_id": to, "amount": amount,
            "note": extra.pop("note", ""), "visibility": extra.pop("visibility", "public"),
            "status": status,
            "expires_at": expires_at or iso(now_utc() + timedelta(hours=2)), **extra}


def fixture(**over):
    """ada 10000, bob 2500, cy 0, dee 5000, op 0 (operator); EUR/2; total 17500."""
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                  user("u_cy", "cy", 0), user("u_dee", "dee", 5000), user("u_op", "op", 0)],
        "payments": [], "requests": [], "authorizations": [],
        "settlement_operator_ids": ["u_op"],
    }
    fx.update(over)
    return fx


def fmt(minor, mu, cur):
    """The spec's formatted amount: exactly mu decimals, one space, the code (D-25)."""
    s = str(int(minor)).rjust(mu + 1, "0")
    return (s if mu == 0 else s[:-mu] + "." + s[-mu:]) + " " + cur


def plain(minor, mu):
    return fmt(minor, mu, "X")[:-2]


def assert_error(resp, status, code=None):
    statuses = status if isinstance(status, (set, tuple, frozenset)) else {status}
    assert resp.status_code in statuses, (resp.status_code, resp.text[:300])
    body = resp.json()
    assert isinstance(body.get("error"), dict) and isinstance(body["error"].get("message"), str)
    if code is not None:
        codes = code if isinstance(code, (set, tuple, frozenset)) else {code}
        assert body["error"].get("code") in codes, body
    return body


def run_parallel(fn, n, workers=None):
    with ThreadPoolExecutor(max_workers=workers or n) as ex:
        return list(ex.map(fn, range(n)))


class Api:
    def __init__(self, base=TARGET_URL):
        self.base = base
        self.http = httpx.Client(base_url=base, timeout=REQUEST_TIMEOUT,
                                 limits=httpx.Limits(max_connections=80,
                                                     max_keepalive_connections=80))

    def call(self, method, path, token=None, key=None, json=None, content=None, headers=None,
             params=None, timeout=None):
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        if key is not None:
            h["Idempotency-Key"] = key
        kw = {"headers": h, "params": params}
        if timeout is not None:
            kw["timeout"] = timeout
        if content is not None:
            kw["content"] = content
            h.setdefault("Content-Type", "application/json")
        elif json is not None:
            kw["json"] = json
        return self.http.request(method, path, **kw)

    def get(self, path, token=None, **kw):
        return self.call("GET", path, token=token, **kw)

    def post(self, path, token=None, key=None, json=None, **kw):
        return self.call("POST", path, token=token, key=key, json=json, **kw)

    def reset(self, fx, expect=204):
        r = self.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
        assert r.status_code == expect, (r.status_code, r.text)
        return r

    def export(self):
        r = self.call("GET", "/_test/export", timeout=CONTROL_TIMEOUT)
        assert r.status_code == 200, r.text
        return r.json()

    def import_(self, obj):
        return self.call("POST", "/_test/import", json=obj, timeout=CONTROL_TIMEOUT)

    def login(self, email, password=PASSWORD):
        r = self.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["token"]

    def me(self, token):
        r = self.get("/me", token)
        assert r.status_code == 200, (r.status_code, r.text)
        m = r.json()
        assert_me_identities(m)
        return m

    def pay(self, token, to, amount, key=None, **f):
        return self.post("/payments", token, key or new_key(),
                         {"to_handle": to, "amount": amount, **f})

    def request(self, token, payer, amount, key=None, **f):
        return self.post("/requests", token, key or new_key(),
                         {"payer_handle": payer, "amount": amount, **f})

    def authorize(self, token, to, amount, key=None, **f):
        return self.post("/authorizations", token, key or new_key(),
                         {"to_handle": to, "amount": amount, **f})

    def capture(self, token, aid, body=None, key=None):
        return self.post(f"/authorizations/{aid}/capture", token, key or new_key(),
                         {} if body is None else body)

    def void(self, token, aid):
        return self.post(f"/authorizations/{aid}/void", token)

    def auths(self, token, **params):
        r = self.get("/authorizations", token, params=params or None)
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    def feed(self, token, **params):
        r = self.get("/activity", token, params=params or None)
        assert r.status_code == 200, r.text
        return r.json()


def assert_me_identities(m):
    """R2-ME.2 / R2-HOLD.6: balance == total, available == total - held >= 0, held >= 0."""
    assert m["balance"] == m["total"], m
    assert m["available"] == m["total"] - m["held"], m
    assert m["available"] >= 0 and m["held"] >= 0, m


class World:
    def __init__(self, api, fx):
        self.api, self.fx = api, fx
        api.reset(fx)
        self.tok = {u["handle"]: api.login(u["email"], u["password"]) for u in fx["users"]}
        self.seeded_total = sum(u["balance"] for u in fx["users"])

    def me(self, h):
        return self.api.me(self.tok[h])

    def mes(self):
        return {h: self.api.me(t) for h, t in self.tok.items()}

    def assert_invariants(self):
        ms = self.mes()
        assert sum(m["total"] for m in ms.values()) == self.seeded_total, ms
        for m in ms.values():
            assert_me_identities(m)
        return ms
