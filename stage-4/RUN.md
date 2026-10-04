# Pocketful — stage 4

Wallet service and browser screens: payments, requests, splits, settlements, payment
authorizations (holds), a bitemporal ledger — historical balances, paginated statements with
frozen snapshots, payment corrections that keep the original receipt — and now refunds by the
receiver and operator correction batches (including whole settlements). One container
serves the JSON API and the screens; every script, stylesheet and font is inside the image.
Python 3.12 standard library only; state is in memory; no network access needed at run time.

## Build and start (one command)

Run from the directory containing this `RUN.md` (the one holding the `Dockerfile`):

```sh
docker build -t pocketful-s4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
```

Or from the repository root:

```sh
docker build -t pocketful-s4 stage-4 && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s4
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` within a second of start, also with `--network none`. Load data with
`POST /_test/reset`.

## What it serves

- Screens (HTML): `/` wallet, `/requests`, `/split`, `/authorizations`, `/signup`, `/login`.
  Files come from `web/`; assets are under `/assets/`. `/requests` and `/authorizations` return
  the screen when the `Accept` header lists `text/html`, JSON otherwise.
- API (JSON): every stage 1 and stage 2 endpoint, plus
  - `GET /me?as_of=<instant>&known_at=<instant>` — balance, total, available and held as they
    stood at `as_of`, as known at `known_at` (both optional RFC 3339 instants with an offset);
  - `GET /statement?from=&to=&known_at=&limit=&offset=` — the caller's payments in `[from, to)`,
    oldest first, with running balances and an opaque `snapshot` token;
    `GET /statement?snapshot=<token>&limit=&offset=` pages that frozen result until the next reset;
  - `POST /payments/{id}/corrections` (idempotent; original sender) and
    `GET /payments/{id}/revisions`;
  - `POST /payments/{id}/refunds` (idempotent; original receiver; body `{"amount": n}`) — a
    new payment in the opposite direction with `refund_of` naming the target and the target's
    note and visibility. Refunds of one payment never exceed its current corrected amount, are
    paid from the receiver's available funds, and cannot themselves be refunded or corrected;
    a correction cannot go below what was already refunded;
  - `POST /correction-batches` (idempotent; settlement operator; body
    `{"corrections": [{payment_id, expected_revision, amount, effective_at, reason}, ...]}`, 1..32
    distinct payments) — corrects several payments in one atomic step. Settlement members may
    only be corrected here, all members of a settlement together with one effective instant;
    captures and refunds stay immutable. The batch is judged on its combined effect (current
    available funds, then every historical boundary); a refused batch changes nothing. All new
    revisions share one `recorded_at` and carry the `correction_batch_id`.
- Server-assigned instants have microsecond precision and strictly increase.
- `POST /_test/import` accepts exports from this team's stage 1, 2, 3 and 4 services. A stage 4
  export carries the statement snapshot tokens, and importing it restores them (stage 1–3
  exports carry none); only a reset ends snapshots.

## Run without Docker

```sh
PORT=8080 python3 -m app.server        # from the directory containing this RUN.md
```

## Tests

From the directory containing this `RUN.md`:

```sh
python3 -m unittest discover -s tests -v
```

Acceptance suites (from the repository root; `STAGE1_URL` and `STAGE2_URL` are your own frozen
stage 1 and stage 2 containers, used as sources of real exports):

```sh
TARGET_URL=http://127.0.0.1:<port> python -m pytest stage-4/acceptance/stage1 -q
TARGET_URL=http://127.0.0.1:<port> STAGE1_URL=http://127.0.0.1:<port1> \
  python -m pytest stage-4/acceptance/stage2 -q
TARGET_URL=http://127.0.0.1:<port> STAGE1_URL=http://127.0.0.1:<port1> \
  STAGE2_URL=http://127.0.0.1:<port2> python -m pytest stage-4/acceptance/stage3 -q
```

## Load and upgrade checks

Against a running container (example on port 18200), from the repository root:

```sh
docker run -d --rm --name pocketful -e PORT=18200 -p 18200:18200 --cpus 2 --memory 2g pocketful-s4
TARGET_URL=http://127.0.0.1:18200 python stage-4/tools/stress.py             # needs httpx
TARGET_URL=http://127.0.0.1:18200 python stage-4/tools/soak.py soak          # needs httpx
TARGET_URL=http://127.0.0.1:18200 HOLDS_SECONDS=60 python3 stage-4/tools/holds_stress.py
TARGET_URL=http://127.0.0.1:18200 LEDGER_SECONDS=60 python3 stage-4/tools/ledger_stress.py
TARGET_URL=http://127.0.0.1:18200 python3 stage-4/tools/ledger_stress.py big
TARGET_URL=http://127.0.0.1:18200 python stage-4/tools/oracle/diff_run.py
STAGE1_URL=http://127.0.0.1:<stage-1 port> STAGE2_URL=http://127.0.0.1:<stage-2 port> \
  STAGE3_URL=http://127.0.0.1:<stage-3 port> STAGE4_URL=http://127.0.0.1:18200 \
  python3 stage-4/tests/upgrade_check4.py
```

`ledger_stress.py` races corrections, re-pages snapshots under writes and checks that balances sum
to the seeded total in every historical view; `big` times reads over 20 000 payments;
`oracle/diff_run.py` diffs the service against an independent reference model;
`upgrade_check4.py` imports populated stage 1, 2 and 3 exports (the frozen services of those
stages) and checks history, statements, corrections, refunds, batches over imported settlements,
sessions, replays and the stage 4 snapshot round trip.
