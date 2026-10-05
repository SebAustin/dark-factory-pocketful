# Replit demo

A public, always-on demo of the band's **stage 4** service. These files are deployment glue
added after the run. They do not change anything in `stage-4/`: the service starts exactly as
its `RUN.md` says (`python3 -m app.server`, no Docker).

| File | What it does |
|---|---|
| [`../.replit`](../.replit) | Python 3.12, run command, port 8080 → 80 |
| [`start.sh`](start.sh) | Starts the service on an internal port, loads the demo data, starts the gateway on `$PORT`, reloads the data every 6 hours |
| [`seed_demo.py`](seed_demo.py) | Loads the band's own acceptance fixture plus a payment, a refund, an open hold and a pending request |
| [`demo_gateway.py`](demo_gateway.py) | Forwards everything to the service except `/_test/*`, which answers 404, so visitors cannot wipe the demo |

**Sign in as** `ada@example.com`, `bob@example.com` or `dee@example.com`, password `correct horse`.

## Deploy

1. On Replit: **Create App → Import from GitHub**, `https://github.com/SebAustin/dark-factory-pocketful`.
2. Press **Run** to try it in the workspace. The log should show `seed: demo data loaded` and
   `demo gateway on 0.0.0.0:8080`.
3. **Publish → Reserved VM** (the smallest machine is enough). Do not choose Autoscale: the
   service keeps its state in memory and must stay a single, always-on instance.
4. Copy the published URL.

Run it locally the same way: `bash replit/start.sh`, then open http://localhost:8080.
