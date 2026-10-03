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
