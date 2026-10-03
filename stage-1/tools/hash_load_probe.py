import asyncio, os, sys, time, random, subprocess
sys.path.insert(0, "/Users/sebastienhenry/dark-factory/band-work/result/stage-1/tools")
from stress import Api, Scenario, setup, key
CT = os.environ["CT"]; DOCKER = "/usr/local/bin/docker"
def cg():
    out = subprocess.run([DOCKER, "exec", CT, "cat", "/sys/fs/cgroup/cpu.stat"], capture_output=True, text=True).stdout.split()
    d = dict(zip(out[::2], map(int, out[1::2]))); return d
def pct(v, q): v = sorted(v); return v[min(len(v)-1, int(q*len(v)))]*1000
async def main():
    api = Api(os.environ["TARGET_URL"]); sc = Scenario("x")
    w = await setup(api, sc, {f"u{i}": 10_000_000 for i in range(20)})
    signed = []
    for i in range(30):
        r = await api.call("POST", "/auth/signup", body={"email": f"s{i}@example.com", "password": "soak-password", "display_name": "S"}); signed.append(f"s{i}@example.com")
    rng = random.Random(1)
    async def worker(kind, end, lat):
        while time.monotonic() < end:
            u = rng.choice(w.users); t = time.monotonic()
            if kind == "login": r = await api.call("POST", "/auth/login", body={"email": rng.choice(signed), "password": "soak-password"})
            elif kind == "signup": r = await api.call("POST", "/auth/signup", body={"email": f"n{rng.random()}@example.com", "password": "soak-password", "display_name": "S"})
            else:
                o = rng.choice([x for x in w.users if x is not u])
                r = await api.call("POST", "/payments", token=u.token, key=key(), body={"to_handle": o.handle, "amount": 1})
            lat.append(time.monotonic() - t)
    async def cond(name, spec, secs=8):
        a = cg(); end = time.monotonic() + secs; lats = {}
        tasks = []
        for kind, k in spec: lats[kind] = []; tasks += [worker(kind, end, lats[kind]) for _ in range(k)]
        await asyncio.gather(*tasks); b = cg()
        parts = [f"{kind}: n={len(l)} p50={pct(l,.5):.0f} p99={pct(l,.99):.0f} max={max(l)*1000:.0f}" for kind, l in lats.items() if l]
        thr = (b["throttled_usec"]-a["throttled_usec"])/1e6; cpu = (b["usage_usec"]-a["usage_usec"])/1e6/secs
        print(f"{name:10s} | " + " | ".join(parts) + f" | cpu={cpu:.2f} cores throttled={b['nr_throttled']-a['nr_throttled']}/{b['nr_periods']-a['nr_periods']} periods ({thr:.1f}s)", flush=True)
    await cond("pay50", [("pay", 50)])
    await cond("auth50", [("signup", 25), ("login", 25)])
    await cond("mix", [("signup", 10), ("login", 10), ("pay", 30)])
    print("5xx", len(api.five_xx), "transport", len(api.transport))
asyncio.run(main())
