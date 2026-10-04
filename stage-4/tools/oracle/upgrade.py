"""Populate a FROZEN stage-1 or stage-2 service with random history and export it (the upgrade path, D-52).

    populate(base_url, stage, seed, ops) -> {"export": <GET /_test/export body>, "writes": [...recorded idempotent writes...],
                                             "tokens": {user_id: token}, "balances": {user_id: balance}}

Stage 2 additionally gets authorizations, partial/final captures and voids; a short authorization_ttl_seconds lets some holds
expire before the export. Stdlib + httpx only.
"""
import random
import time

import httpx

PASSWORD = "correct horse"


class Source:
    def __init__(self, base, stage, seed):
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=20)
        self.stage = stage
        self.rng = random.Random(seed)
        self.writes = []
        self.keys = 0
        self.tokens = {}
        self.handles = {}
        self.users = []

    def call(self, method, path, token=None, body=None, key=None, params=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        r = self.http.request(method, path, headers=headers, json=body, params=params)
        try:
            data = r.json() if r.content else None
        except ValueError:
            data = None
        return r.status_code, data

    def write(self, path, token, body, user=None):
        self.keys += 1
        key = f"src-{self.keys}"
        status, resp = self.call("POST", path, token, body, key)
        if status in (200, 201):
            self.writes.append({"path": path, "key": key, "body": body, "user": user, "response": resp})
        return status, resp

    def setup(self, n_users=6):
        balances = [50000, 50000, 50000, 2000, 500, 400]
        users = [{"id": f"u_{i}", "email": f"u{i}@example.com", "password": PASSWORD, "display_name": f"U{i}", "handle": f"u{i}", "balance": balances[i]}
                 for i in range(n_users)]
        fixture = {"currency": "EUR", "minor_units": 2, "users": users, "payments": [], "requests": [], "settlement_operator_ids": ["u_0"]}
        if self.stage >= 2:
            fixture["authorization_ttl_seconds"] = 5
        status, _ = self.call("POST", "/_test/reset", body=fixture)
        assert status == 204, f"source reset returned {status}"
        self.users = [u["id"] for u in users]
        for u in users:
            status, body = self.call("POST", "/auth/login", body={"email": u["email"], "password": PASSWORD})
            self.tokens[u["id"]] = body["token"]
            self.handles[u["id"]] = u["handle"]

    def run(self, ops):
        rng = self.rng
        auths = []
        for i in range(ops):
            kind = rng.random()
            frm, to = rng.sample(self.users, 2)
            if kind < 0.45:
                for _ in range(rng.choice([1, 1, 3])):         # same-second bursts
                    self.write("/payments", self.tokens[frm], {"to_handle": self.handles[to], "amount": rng.choice([1, 5, 20, 100]), "note": "src",
                                                              "visibility": rng.choice(["public", "private"])}, frm)
            elif kind < 0.6:
                st, rq = self.write("/requests", self.tokens[to], {"payer_handle": self.handles[frm], "amount": rng.choice([10, 30]), "note": "rq"}, to)
                if st == 201:
                    how = rng.choice(["pay", "pay", "decline", "cancel"])
                    if how == "pay":
                        self.write(f"/requests/{rq['request_id']}/pay", self.tokens[frm], {"visibility": "public"}, frm)
                    else:
                        self.call("POST", f"/requests/{rq['request_id']}/{how}", self.tokens[frm if how == 'decline' else to])
            elif kind < 0.68:
                handles = [self.handles[u] for u in rng.sample(self.users, 3)]
                self.write("/splits", self.tokens[frm], {"amount": rng.choice([100, 301]), "participant_handles": handles, "note": "split"}, frm)
            elif kind < 0.76:
                picks = rng.sample(self.users, 3)
                transfers = [{"from_handle": self.handles[picks[0]], "to_handle": self.handles[picks[1]], "amount": 10},
                             {"from_handle": self.handles[picks[1]], "to_handle": self.handles[picks[2]], "amount": 5}]
                self.write("/settlements", self.tokens["u_0"], {"transfers": transfers}, "u_0")
            elif self.stage >= 2 and kind < 0.88:
                st, resp = self.write("/authorizations", self.tokens[frm], {"to_handle": self.handles[to], "amount": rng.choice([50, 200]), "note": "hold"}, frm)
                if st == 201:
                    auths.append((resp["authorization_id"], frm, to, resp["amount"], 0))
            elif self.stage >= 2 and auths:
                aid, afrm, ato, amount, taken = rng.choice(auths)
                if rng.random() < 0.3:
                    self.call("POST", f"/authorizations/{aid}/void", self.tokens[afrm])
                else:
                    cap = min(amount - taken, rng.choice([10, 25, amount]))
                    if cap > 0:
                        body = {"amount": cap}
                        if rng.random() < 0.5:
                            body["final"] = False
                        st, resp = self.write(f"/authorizations/{aid}/capture", self.tokens[ato], body, ato)
            if rng.random() < 0.2:
                time.sleep(rng.choice([0.3, 1.1]))
        if self.stage >= 3:
            self.corrections()

    def corrections(self):
        """Stage 3 corrections (single path) so the export carries revisions: recorded in `writes` for verbatim replay."""
        from datetime import datetime, timedelta, timezone
        rng = self.rng
        pays = [w for w in self.writes if w["path"] == "/payments" and w["user"] in self.tokens]
        time.sleep(1.5)
        for w in rng.sample(pays, min(12, len(pays))):
            pid, amount = w["response"]["payment_id"], w["response"]["amount"]
            eff = (datetime.now(timezone.utc) - timedelta(seconds=rng.randrange(1, 4))).isoformat(timespec="seconds")
            for _ in range(rng.choice([1, 1, 2])):
                st, rev = self.call("GET", f"/payments/{pid}/revisions", self.tokens[w["user"]])
                if st != 200:
                    break
                body = {"expected_revision": len(rev["revisions"]), "amount": rng.choice([0, max(amount - 1, 0), amount + 1]), "effective_at": eff, "reason": "src correction"}
                self.write(f"/payments/{pid}/corrections", self.tokens[w["user"]], body, w["user"])

    def export(self):
        status, body = self.call("GET", "/_test/export")
        assert status == 200, f"source export returned {status}"
        return body


def populate(base, stage, seed, ops):
    src = Source(base, stage, seed)
    src.setup()
    src.run(ops)
    time.sleep(6 if stage == 2 else 1)          # let short holds expire before the export
    export = src.export()
    balances = {}
    for u in src.users:
        status, me = src.call("GET", "/me", src.tokens[u])
        balances[u] = me["balance"]
    return {"export": export, "writes": src.writes, "tokens": src.tokens, "balances": balances, "handles": src.handles}
