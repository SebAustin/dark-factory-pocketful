#!/usr/bin/env python3
"""Soak and size tests for a running Pocketful stage 1 service.

    TARGET_URL=http://127.0.0.1:18300 python stage-1/tools/soak.py soak   # default
    TARGET_URL=... python stage-1/tools/soak.py big

soak: 50 in flight for STRESS_SECONDS (default 60) of mixed writes and reads including signups
      and logins (scrypt), balance sampling during the load, per-endpoint latency, and the
      invariant checks of stress.py at the end. Fails on any 5xx, any request slower than 5 s,
      any 4xx without the error envelope, or any broken invariant.
big:  reset with 1000 and 2000 users (distinct passwords) and export/import of a state with
      5000+ payments and their idempotency records, each of which must take under 10 s.
Needs stdlib and httpx; reuses the client and checks of stress.py (same folder).
"""
import asyncio
import os
import sys
import time

from stress import Api, MAX_IN_FLIGHT, Mixed, RESET_TIMEOUT, Scenario, World, key, setup

SLOW = 5.0
BIG_PAYMENTS = 5000


class SoakMixed(Mixed):
    WEIGHTS = Mixed.WEIGHTS + [("signup", 6), ("login", 6)]

    def __init__(self, *a):
        super().__init__(*a)
        self.accounts = [(f"{u.handle}@example.com", "correct horse") for u in self.w.users]
        self.signups = 0
        self.tokens = []

    async def op_signup(self):
        self.signups += 1
        email = f"soak{self.signups}x{id(self) % 997}@example.com"
        r = await self.api.call("POST", "/auth/signup", body={
            "email": email, "password": "soak-password", "display_name": "Soak"})
        if self.sc.expect(r, {201}, "signup"):
            self.accounts.append((email, "soak-password"))
            self.tokens.append(r.json["token"])

    async def op_login(self):
        email, password = self.rng.choice(self.accounts)
        r = await self.api.call("POST", "/auth/login", body={"email": email, "password": password})
        self.sc.expect(r, {200}, "login")


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def latency_table(api):
    print(f"\n{'endpoint':<34}{'n':>7}{'p50 ms':>9}{'p99 ms':>9}{'max ms':>9}")
    for label, vals in sorted(api.latency.items(), key=lambda kv: -len(kv[1])):
        print(f"{label:<34}{len(vals):>7}{percentile(vals, .5) * 1000:>9.1f}"
              f"{percentile(vals, .99) * 1000:>9.1f}{max(vals) * 1000:>9.1f}")


def transport_problems(api, sc):
    for label, items in (("5xx", api.five_xx), ("4xx without error envelope", api.bad_envelope),
                         ("timeout or connection failure", api.transport)):
        if items:
            sc.check(False, f"{len(items)} x {label}, first: {items[0]}")
    slow = [(m, max(v)) for m, v in api.latency.items() if max(v) > SLOW]
    for label, worst in slow:
        sc.check(False, f"{label} took {worst:.1f}s (limit {SLOW:.0f}s)")


async def soak(api, sc):
    seconds = float(os.environ.get("STRESS_SECONDS", "60"))
    w = await setup(api, sc, {f"u{i}": 100000 for i in range(20)}, operators=["u0"])
    m = SoakMixed(api, sc, w, seconds)
    began = time.monotonic()
    await m.run()
    took = time.monotonic() - began
    await m.final_checks()
    sc.notes.append(f"{m.ops} ops in {took:.0f}s, {m.signups} signups, {len(m.reqs)} requests")
    transport_problems(api, sc)


async def timed(api, sc, label, method, path, limit=RESET_TIMEOUT, **kw):
    began = time.monotonic()
    r = await api.call(method, path, timeout=limit + 5, **kw)
    took = time.monotonic() - began
    sc.check(took < limit, f"{label} took {took:.1f}s (limit {limit:.0f}s)")
    sc.notes.append(f"{label} {took:.2f}s")
    return r, took


def users_fixture(n):
    return {"currency": "EUR", "minor_units": 2, "payments": [], "requests": [],
            "users": [{"id": f"u_{i}", "email": f"user{i}@example.com", "password": f"pw-{i}-distinct-x",
                       "display_name": f"U{i}", "handle": f"user{i}", "balance": 1000} for i in range(n)]}


async def reset_size(api, sc, n):
    r, _ = await timed(api, sc, f"reset {n} users", "POST", "/_test/reset", body=users_fixture(n))
    sc.expect(r, {204}, f"reset {n} users")
    for i in (0, n - 1):
        r = await api.call("POST", "/auth/login", body={"email": f"user{i}@example.com",
                                                          "password": f"pw-{i}-distinct-x"})
        sc.expect(r, {200}, f"login of seeded user {i} after a {n} user reset")


async def reset_1000(api, sc):
    await reset_size(api, sc, 1000)


async def reset_2000(api, sc):
    await reset_size(api, sc, 2000)


async def export_import(api, sc):
    w = await setup(api, sc, {f"u{i}": 10_000_000 for i in range(50)})
    jobs = [(w.users[i % 50], w.users[(i + 1) % 50], f"bulk-{i}") for i in range(BIG_PAYMENTS)]
    queue = asyncio.Queue()
    for j in jobs:
        queue.put_nowait(j)

    async def worker():
        while not queue.empty():
            a, b, k = queue.get_nowait()
            r = await api.call("POST", "/payments", token=a.token, key=k,
                               body={"to_handle": b.handle, "amount": 3, "note": "bulk " + "n" * 50})
            sc.expect(r, {201}, "bulk payment")

    began = time.monotonic()
    await asyncio.gather(*[worker() for _ in range(MAX_IN_FLIGHT)])
    sc.notes.append(f"{BIG_PAYMENTS} payments in {time.monotonic() - began:.1f}s")
    before = await w.balances(sc)
    r, _ = await timed(api, sc, "export", "GET", "/_test/export")
    if not sc.expect(r, {200}, "export"):
        return
    snap, size = r.json, len(r.text)
    sc.notes.append(f"export {size / 1e6:.1f} MB")
    await api.call("POST", "/_test/reset", body=users_fixture(3), timeout=RESET_TIMEOUT)
    r, _ = await timed(api, sc, "import", "POST", "/_test/import", body=snap)
    sc.expect(r, {204}, "import")
    after = await w.balances(sc)
    sc.check(after == before, "balances after import differ from balances at export")
    again = await api.call("POST", "/payments", token=w.users[0].token, key="bulk-0",
                           body={"to_handle": w.users[1].handle, "amount": 3, "note": "bulk " + "n" * 50})
    sc.check(again.status == 200, f"replay of a pre-export payment after import: {again.status}")


PHASES = {
    "soak": [("soak: 50 in flight, mixed + signup/login", soak)],
    "big": [("reset with 1000 users", reset_1000), ("reset with 2000 users", reset_2000),
            (f"export/import {BIG_PAYMENTS} payments", export_import)],
}


async def main():
    target = os.environ.get("TARGET_URL")
    mode = sys.argv[1] if len(sys.argv) > 1 else "soak"
    if not target or mode not in PHASES:
        print("usage: TARGET_URL=http://host:port soak.py [soak|big]", file=sys.stderr)
        return 2
    api = Api(target.rstrip("/"))
    failed = 0
    for name, fn in PHASES[mode]:
        sc = Scenario(name)
        began = time.monotonic()
        try:
            await fn(api, sc)
        except Exception as exc:
            sc.check(False, f"aborted: {type(exc).__name__}: {exc}")
        print(f"{'PASS' if not sc.fail_count else 'FAIL'}  {name}  ({time.monotonic() - began:.1f}s)  "
              f"{'; '.join(sc.notes)}")
        for msg in sc.fails:
            print("    -", msg)
        failed += bool(sc.fail_count)
    if mode == "soak":
        latency_table(api)
    await api.client.aclose()
    print(f"\n{api.count} requests, {len(api.five_xx)} 5xx, {len(api.bad_envelope)} bad error bodies, "
          f"{len(api.transport)} timeouts/failures")
    return 1 if failed or api.five_xx or api.transport else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
