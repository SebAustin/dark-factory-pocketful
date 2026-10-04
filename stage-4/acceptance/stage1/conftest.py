"""Shared helpers for the stage 1 acceptance suite.

Black box: every test drives the service only over HTTP at TARGET_URL and starts from its
own `POST /_test/reset`. Expected values come from the specification (runlog/stage1-spec.md)
and the ledger (stage-1/docs/ledger.md); each test names the requirement ids it proves.
"""
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

TARGET_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:18100").rstrip("/")
PASSWORD = "correct horse"
REQUEST_TIMEOUT = 5.0  # §2 per-request timeout
CONTROL_TIMEOUT = 10.0  # §2 / §10 test control calls

RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)

PAYMENT_KEYS = {
    "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
    "currency", "note", "visibility", "request_id", "created_at", "settlement_id",
    # stage 2 (R2-CAP.6, decision D-39): every payment object carries authorization_id
    "authorization_id",
}
REQUEST_KEYS = {
    "request_id", "requester_id", "requester_handle", "payer_id", "payer_handle", "amount",
    "currency", "note", "status", "payment_id", "created_at",
}


def user(uid, handle, balance, **extra):
    return {
        "id": uid, "email": f"{handle}@example.com", "password": PASSWORD,
        "display_name": handle.capitalize(), "handle": handle, "balance": balance, **extra,
    }


def base_fixture(**over):
    """Default world: ada 10000, bob 2500, cy 0, dee 5000 (EUR, 2). Total 17500."""
    fx = {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            user("u_ada", "ada", 10000),
            user("u_bob", "bob", 2500),
            user("u_cy", "cy", 0),
            user("u_dee", "dee", 5000),
        ],
        "payments": [],
        "requests": [],
    }
    fx.update(over)
    return fx


class Api:
    """Thin HTTP client; thread-safe (httpx.Client is)."""

    def __init__(self):
        self.http = httpx.Client(
            base_url=TARGET_URL,
            timeout=REQUEST_TIMEOUT,
            limits=httpx.Limits(max_connections=80, max_keepalive_connections=80),
        )

    def call(self, method, path, token=None, key=None, json=None, content=None,
             headers=None, params=None, timeout=None):
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        if key is not None:
            h["Idempotency-Key"] = key
        kwargs = {"headers": h, "params": params}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if content is not None:
            kwargs["content"] = content
            h.setdefault("Content-Type", "application/json")
        elif json is not None:
            kwargs["json"] = json
        return self.http.request(method, path, **kwargs)

    def get(self, path, token=None, **kw):
        return self.call("GET", path, token=token, **kw)

    def post(self, path, token=None, key=None, json=None, **kw):
        return self.call("POST", path, token=token, key=key, json=json, **kw)

    # ---- control ----
    def reset(self, fixture):
        r = self.call("POST", "/_test/reset", json=fixture, timeout=CONTROL_TIMEOUT)
        assert r.status_code == 204, (r.status_code, r.text)
        return r

    def login(self, email, password=PASSWORD):
        r = self.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["token"]

    def me(self, token):
        r = self.get("/me", token)
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    def balance(self, token):
        return self.me(token)["balance"]

    # ---- domain shortcuts (always fresh keys) ----
    def pay(self, token, to, amount, key=None, **fields):
        return self.post("/payments", token, key or new_key(),
                         {"to_handle": to, "amount": amount, **fields})

    def request(self, token, payer, amount, key=None, **fields):
        return self.post("/requests", token, key or new_key(),
                         {"payer_handle": payer, "amount": amount, **fields})

    def pay_request(self, token, rid, body=None, key=None):
        return self.post(f"/requests/{rid}/pay", token, key or new_key(),
                         {} if body is None else body)

    def feed(self, token, **params):
        r = self.get("/activity", token, params=params or None)
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()

    def requests_list(self, token, **params):
        r = self.get("/requests", token, params=params or None)
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()


class World:
    """A reset service plus a token per seeded handle."""

    def __init__(self, api, fixture):
        self.api = api
        self.fixture = fixture
        api.reset(fixture)
        self.tok = {u["handle"]: api.login(u["email"], u["password"]) for u in fixture["users"]}
        self.ids = {u["handle"]: u["id"] for u in fixture["users"]}
        self.seeded_total = sum(u["balance"] for u in fixture["users"])

    def total(self):
        return sum(self.api.balance(t) for t in self.tok.values())

    def balances(self):
        return {h: self.api.balance(t) for h, t in self.tok.items()}

    def assert_invariants(self):
        """R-1.6 sum conserved, R-1.7 no negative balance."""
        b = self.balances()
        assert all(v >= 0 for v in b.values()), b
        assert sum(b.values()) == self.seeded_total, b


def new_key():
    return "k-" + uuid.uuid4().hex


def assert_error(resp, status, code=None):
    """R-5.1/R-5.2: specified status and code inside the error envelope.

    `status`/`code` may be a set where the specification is open (decision records)."""
    statuses = status if isinstance(status, (set, tuple, frozenset)) else {status}
    assert resp.status_code in statuses, (resp.status_code, resp.text)
    body = resp.json()
    assert isinstance(body, dict) and isinstance(body.get("error"), dict), body
    assert isinstance(body["error"].get("message"), str), body
    if code is not None:
        codes = code if isinstance(code, (set, tuple, frozenset)) else {code}
        assert body["error"].get("code") in codes, body
    return body


def run_parallel(fn, n, workers=None):
    with ThreadPoolExecutor(max_workers=workers or n) as ex:
        return list(ex.map(lambda i: fn(i), range(n)))


@pytest.fixture(scope="session")
def api():
    a = Api()
    yield a
    a.http.close()


@pytest.fixture
def world(api):
    return World(api, base_fixture())


@pytest.fixture
def make_world(api):
    def _make(fixture=None, **over):
        return World(api, fixture if fixture is not None else base_fixture(**over))
    return _make
