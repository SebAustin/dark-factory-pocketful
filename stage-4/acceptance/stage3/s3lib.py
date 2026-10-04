"""Stage 3 acceptance helpers: HTTP client, instants, and the analyst's reference model.

The model implements decisions D-48 (two-time selection) and D-51 (historical holds) directly from
the specification. It is fed only with facts the service reports (instants in responses) and the
fixture; every balance it predicts is computed independently and compared with the service.
"""
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

TARGET_URL = os.environ.get("TARGET_URL", "http://127.0.0.1:18100").rstrip("/")
STAGE1_URL = os.environ.get("STAGE1_URL", "http://127.0.0.1:18101").rstrip("/")
STAGE2_URL = os.environ.get("STAGE2_URL", "http://127.0.0.1:18102").rstrip("/")
PASSWORD = "correct horse"
TIMEOUT = 5.0
CONTROL_TIMEOUT = 10.0
UTC = timezone.utc
NEG_INF = -(10 ** 30)
POS_INF = 10 ** 30

RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?([Zz]|([+-])(\d{2}):(\d{2}))$")

PAYMENT_KEYS = {
    "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
    "currency", "note", "visibility", "request_id", "created_at", "settlement_id",
    "authorization_id",
}
REVISION_KEYS = {"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}
ENTRY_KEYS = {"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"}


# ---------------------------------------------------------------- instants (D-42)

def ns(value):
    """Exact nanoseconds since the epoch for an RFC 3339 string with offset."""
    m = RFC3339.match(value)
    assert m, f"not RFC 3339 with offset: {value!r}"
    y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(8) or "").ljust(9, "0")
    base = datetime(y, mo, d, hh, mi, ss, tzinfo=UTC)
    off = 0
    if m.group(9) not in ("Z", "z"):
        off = (int(m.group(11)) * 60 + int(m.group(12))) * 60 * (1 if m.group(10) == "+" else -1)
    secs = int((base - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()) - off
    return secs * 10 ** 9 + int(frac)


def iso_ns(t, offset_minutes=0):
    """Render nanoseconds as RFC 3339 with 9 fractional digits in the given offset."""
    secs, frac = divmod(t, 10 ** 9)
    dt = datetime.fromtimestamp(secs, UTC) + timedelta(minutes=offset_minutes)
    sign = "+" if offset_minutes >= 0 else "-"
    om = abs(offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac:09d}{sign}{om // 60:02d}:{om % 60:02d}"


def now_ns():
    return int(datetime.now(UTC).timestamp() * 10 ** 6) * 1000


def iso(dt):
    return dt.astimezone(UTC).isoformat()


US = 1000  # one microsecond in ns


def new_key():
    return "k-" + uuid.uuid4().hex


def user(uid, handle, balance, **extra):
    return {"id": uid, "email": f"{handle}@example.com", "password": PASSWORD,
            "display_name": handle.capitalize(), "handle": handle, "balance": balance, **extra}


def run_parallel(fn, n, workers=None):
    with ThreadPoolExecutor(max_workers=workers or n) as ex:
        return list(ex.map(fn, range(n)))


def assert_error(resp, status, code=None):
    statuses = status if isinstance(status, (set, tuple, frozenset)) else {status}
    assert resp.status_code in statuses, (resp.status_code, resp.text[:300])
    body = resp.json()
    assert isinstance(body.get("error"), dict) and isinstance(body["error"].get("message"), str)
    if code is not None:
        codes = code if isinstance(code, (set, tuple, frozenset)) else {code}
        assert body["error"].get("code") in codes, body
    return body


# ---------------------------------------------------------------- HTTP

class Api:
    def __init__(self, base=TARGET_URL):
        self.http = httpx.Client(base_url=base, timeout=TIMEOUT,
                                 limits=httpx.Limits(max_connections=80,
                                                     max_keepalive_connections=80))

    def call(self, method, path, token=None, key=None, json=None, content=None, params=None,
             headers=None, timeout=None):
        h = dict(headers or {})
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        if key is not None:
            h["Idempotency-Key"] = key
        kw = {"headers": h, "params": params}
        if timeout:
            kw["timeout"] = timeout
        if content is not None:
            kw["content"] = content
            h.setdefault("Content-Type", "application/json")
        elif json is not None:
            kw["json"] = json
        return self.http.request(method, path, **kw)

    def reset(self, fx, expect=204):
        r = self.call("POST", "/_test/reset", json=fx, timeout=CONTROL_TIMEOUT)
        assert r.status_code == expect, (r.status_code, r.text[:300])
        return r

    def export(self):
        r = self.call("GET", "/_test/export", timeout=CONTROL_TIMEOUT)
        assert r.status_code == 200
        return r.json()

    def import_(self, obj):
        return self.call("POST", "/_test/import", json=obj, timeout=CONTROL_TIMEOUT)

    def login(self, email):
        r = self.call("POST", "/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def me(self, token, **params):
        r = self.call("GET", "/me", token, params=params or None)
        assert r.status_code == 200, (r.status_code, r.text[:300], params)
        return r.json()

    def pay(self, token, to, amount, **f):
        r = self.call("POST", "/payments", token, new_key(), {"to_handle": to, "amount": amount,
                                                            **f})
        return r

    def correct(self, token, pid, expected, amount, effective_at, reason="fix", key=None):
        return self.call("POST", f"/payments/{pid}/corrections", token, key or new_key(),
                         {"expected_revision": expected, "amount": amount,
                          "effective_at": effective_at, "reason": reason})

    def revisions(self, token, pid):
        return self.call("GET", f"/payments/{pid}/revisions", token)

    def statement(self, token, **params):
        return self.call("GET", "/statement", token, params=params or None)

    def statement_all(self, token, limit=7, **params):
        """First page plus every snapshot page; returns (first_body, all_entries)."""
        r = self.statement(token, limit=limit, **params)
        assert r.status_code == 200, (r.status_code, r.text[:300], params)
        first = r.json()
        entries = list(first["entries"])
        off = limit
        more = first["has_more"]
        while more:
            p = self.statement(token, snapshot=first["snapshot"], limit=limit, offset=off)
            assert p.status_code == 200, p.text
            body = p.json()
            entries += body["entries"]
            more = body["has_more"]
            off += limit
        return first, entries


# ---------------------------------------------------------------- reference model (D-48, D-51)

class Model:
    def __init__(self, openings):
        self.opening = dict(openings)       # user id -> opening balance
        self.payments = {}                  # id -> {from, to, revs: [(rev, amount, eff, rec)]}
        self.auths = {}                     # id -> {from, amount, created, expires, events}

    # facts --------------------------------------------------------
    def add_payment(self, p):
        """p: a payment object from the service (revision 1)."""
        t = ns(p["created_at"])
        self.payments[p["payment_id"]] = {"from": p["from_user_id"], "to": p["to_user_id"],
                                          "revs": [(1, p["amount"], t, t)]}

    def add_revision(self, r):
        self.payments[r["payment_id"]]["revs"].append(
            (r["revision"], r["amount"], ns(r["effective_at"]), ns(r["recorded_at"])))

    def add_auth(self, a):
        self.auths[a["authorization_id"]] = {
            "from": a["from_user_id"], "amount": a["amount"], "created": ns(a["created_at"]),
            "expires": ns(a["expires_at"]), "events": []}

    def capture_event(self, aid, payment, final):
        t = ns(payment["created_at"])
        self.auths[aid]["events"].append((t, "capture", payment["amount"], final))
        self.add_payment(payment)

    def void_event(self, aid, closed_at):
        self.auths[aid]["events"].append((ns(closed_at), "void", 0, True))

    # views --------------------------------------------------------
    def selected(self, pid, K):
        best = None
        for rev in self.payments[pid]["revs"]:
            if rev[3] <= K and (best is None or rev[3] > best[3]):
                best = rev
        return best

    def balance(self, u, T, K):
        b = self.opening.get(u, 0)
        for pid, p in self.payments.items():
            if u not in (p["from"], p["to"]):
                continue
            s = self.selected(pid, K)
            if s is None or s[2] > T:
                continue
            b += -s[1] if p["from"] == u else s[1]
        return b

    def held(self, u, T, K):
        total = 0
        for a in self.auths.values():
            if a["from"] != u or a["created"] > K or a["created"] > T:
                continue
            h = a["amount"]
            open_ = True
            for t, kind, amt, final in sorted(a["events"]):
                if t > K or t > T:
                    break
                if kind == "capture":
                    h -= amt
                    if final or h == 0:
                        open_ = False
                else:
                    open_ = False
                if not open_:
                    break
            if open_ and T >= a["expires"]:
                open_ = False
            total += h if open_ else 0
        return total

    def view(self, u, T, K):
        total = self.balance(u, T, K)
        held = self.held(u, T, K)
        return {"balance": total, "total": total, "held": held, "available": total - held}

    def statement(self, u, frm, to, K):
        rows = []
        for pid, p in self.payments.items():
            if u not in (p["from"], p["to"]):
                continue
            s = self.selected(pid, K)
            if s is None:
                continue
            rows.append((s[2], pid, -s[1] if p["from"] == u else s[1], s))
        opening = self.opening.get(u, 0) + sum(d for e, _, d, _ in rows if e < frm)
        window = sorted((r for r in rows if frm <= r[0] < to), key=lambda r: (r[0], r[1]))
        out, bal = [], opening
        for e, pid, d, s in window:
            bal += d
            out.append({"payment_id": pid, "delta": d, "balance_after": bal, "revision": s[0],
                        "amount": s[1]})
        return {"opening_balance": opening, "entries": out, "closing_balance": bal}

    def boundaries(self):
        pts = set()
        for p in self.payments.values():
            for _, _, e, r in p["revs"]:
                pts.add(e)
                pts.add(r)
        for a in self.auths.values():
            pts.add(a["created"])
            pts.add(a["expires"])
            for ev in a["events"]:
                pts.add(ev[0])
        return sorted(pts)

    def recorded_points(self):
        pts = {r for p in self.payments.values() for _, _, _, r in p["revs"]}
        pts |= {a["created"] for a in self.auths.values()}
        pts |= {ev[0] for a in self.auths.values() for ev in a["events"]}
        return sorted(pts)


class World:
    """Reset + tokens + a model seeded with the fixture's openings and seeded payments."""

    def __init__(self, api, fx):
        self.api, self.fx = api, fx
        api.reset(fx)
        self.tok = {u["handle"]: api.login(u["email"]) for u in fx["users"]}
        self.uid = {u["handle"]: u["id"] for u in fx["users"]}
        self.seeded_total = sum(u["balance"] for u in fx["users"])
        openings = {u["id"]: u["balance"] for u in fx["users"]}
        for p in fx.get("payments", []):
            openings[p["from_user_id"]] += p["amount"]
            openings[p["to_user_id"]] -= p["amount"]
        self.model = Model(openings)
        # learn seeded payments' created_at from the service (reset time when omitted)
        seen = set()
        for h, t in self.tok.items():
            r = api.call("GET", "/activity", t, params={"limit": 200})
            assert r.status_code == 200, r.text
            for p in r.json()["payments"]:
                if p["payment_id"] not in seen:
                    seen.add(p["payment_id"])
                    self.model.add_payment(p)

    def pay(self, frm, to, amount, **f):
        r = self.api.pay(self.tok[frm], to, amount, **f)
        assert r.status_code == 201, r.text
        self.model.add_payment(r.json())
        return r.json()

    def correct(self, frm, pid, expected, amount, effective_at, reason="fix"):
        r = self.api.correct(self.tok[frm], pid, expected, amount, effective_at, reason)
        if r.status_code == 201:
            self.model.add_revision(r.json())
        return r


def base_fixture(**over):
    """Seeded history in the past: openings ada 12000, bob 2000, cy 0, dee 5000, op 0."""
    t0 = datetime.now(UTC) - timedelta(hours=3)
    fx = {
        "currency": "EUR", "minor_units": 2,
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                  user("u_cy", "cy", 1500), user("u_dee", "dee", 5000), user("u_op", "op", 0)],
        "payments": [
            {"id": "p_s1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
             "note": "seed one", "visibility": "public",
             "created_at": iso(t0)},
            {"id": "p_s2", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 1500,
             "note": "seed two", "visibility": "private",
             "created_at": iso(t0 + timedelta(minutes=30))},
        ],
        "requests": [], "authorizations": [], "settlement_operator_ids": ["u_op"],
    }
    fx.update(over)
    return fx


# ---------------------------------------------------------------- model: correction verdicts (D-46/D-53)

def model_correction_verdict(model, pid, new_amount, eff, now):
    """None (accepted), 'insufficient_funds' or 'historical_overdraft' per D-46/D-53."""
    p = model.payments[pid]
    cur = max(p["revs"], key=lambda r: r[3])
    diff = new_amount - cur[1]
    debited = p["from"] if diff > 0 else p["to"]
    if diff != 0:
        v = model.view(debited, now, now)
        if v["available"] < abs(diff):
            return "insufficient_funds"
    p["revs"].append((cur[0] + 1, new_amount, eff, now))
    try:
        for u in (p["from"], p["to"]):
            pts = [b for b in model.boundaries() if b <= now]
            for b in [NEG_INF] + pts:
                v = model.view(u, b, POS_INF)
                if v["total"] < 0 or v["available"] < 0:
                    return "historical_overdraft"
    finally:
        p["revs"].pop()
    return None
