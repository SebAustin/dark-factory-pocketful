# Pocketful — stage 2

Wallet service and browser screens: payments, requests, splits, settlements, and payment
authorizations (holds that are captured later, voided, or expire). One container serves the
JSON API and the screens; every script, stylesheet and font is inside the image. Python 3.12
standard library only; state is in memory; no network access needed at run time.

## Build and start (one command)

Run from the directory containing this `RUN.md` (the one holding the `Dockerfile`):

```sh
docker build -t pocketful-s2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2
```

Or from the repository root:

```sh
docker build -t pocketful-s2 stage-2 && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s2
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` within a second of start, also with `--network none`. Load data with
`POST /_test/reset`.

## What it serves

- Screens (HTML): `/` wallet (available, total and held funds; pay, request and authorize forms;
  activity), `/requests`, `/split`, `/authorizations`, `/signup`, `/login`. Files come from
  `web/`; assets are under `/assets/`.
- API (JSON): every stage 1 endpoint, plus `POST /authorizations`, `GET /authorizations`,
  `POST /authorizations/{id}/capture` and `POST /authorizations/{id}/void`. `GET /me` adds
  `total`, `available` and `held`.
- `/requests` and `/authorizations` are shared: a request whose `Accept` header lists
  `text/html` gets the screen, anything else gets JSON.
- `POST /_test/import` accepts an export from this team's stage 1 service (upgrade path) as well
  as a stage 2 export.

## Run without Docker

```sh
PORT=8080 python3 -m app.server        # from the directory containing this RUN.md
```

## Tests

From the directory containing this `RUN.md`:

```sh
python3 -m unittest discover -s tests -v
```

Acceptance suites (from the repository root; `STAGE1_URL` is your own frozen stage 1
container, used as the source of a real stage 1 export):

```sh
TARGET_URL=http://127.0.0.1:<port> python -m pytest stage-2/acceptance/stage1 -q
TARGET_URL=http://127.0.0.1:<port> STAGE1_URL=http://127.0.0.1:<port1> \
  python -m pytest stage-2/acceptance/stage2 -q
```

## Load and upgrade checks

Against a running container (example on port 18200), from the repository root:

```sh
docker run -d --rm --name pocketful -e PORT=18200 -p 18200:18200 --cpus 2 --memory 2g pocketful-s2
TARGET_URL=http://127.0.0.1:18200 python stage-2/tools/stress.py             # needs httpx
TARGET_URL=http://127.0.0.1:18200 python stage-2/tools/soak.py soak          # needs httpx
TARGET_URL=http://127.0.0.1:18200 HOLDS_SECONDS=60 python3 stage-2/tools/holds_stress.py
STAGE1_URL=http://127.0.0.1:<stage-1 port> STAGE2_URL=http://127.0.0.1:18200 \
  python3 stage-2/tests/upgrade_check.py
```

`stress.py` and `soak.py` cover the stage 1 invariants under 50 requests in flight;
`holds_stress.py` adds authorizations, captures, voids and expiry under load (available never
negative, totals conserved, captures add up); `upgrade_check.py` imports a real stage 1 export
and checks sessions, pending requests and retries survive.
