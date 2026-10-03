# Pocketful — stage 1

HTTP service for payments, requests, splits and settlements. Python 3.12 standard library only;
state is in memory; no network access needed at run time.

## Build and start (one command, from the repository root)

```sh
docker build -t pocketful-s1 stage-1 && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-s1
```

The service listens on `0.0.0.0:$PORT` (default `8080`) and answers `GET /health` with
`200 {"status":"ok"}` within a second of start. Load data with `POST /_test/reset`.

## Run without Docker

```sh
cd stage-1 && PORT=8080 python3 -m app.server
```

## Tests

```sh
cd stage-1 && python3 -m unittest discover -s tests -v
```

## Load check (S1.8)

Against a running container (example on port 18200):

```sh
docker run -d --rm --name pocketful -e PORT=18200 -p 18200:18200 --cpus 2 --memory 2g pocketful-s1
TARGET_URL=http://127.0.0.1:18200 SOAK_SECONDS=60 python3 stage-1/tests/soak.py
```

It checks a 1000-user reset inside 10 s, a burst of 50 signups and 50 logins, then 50
in-flight mixed operations: no 5xx, no response over 5 s, no negative balance, total unchanged.
