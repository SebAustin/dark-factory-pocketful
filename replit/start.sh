#!/usr/bin/env bash
# Start the Replit demo of stage 4 (deployment glue, not part of the band's output).
#   1. the band's stage 4 service, unchanged, on an internal port (started as its RUN.md says)
#   2. the demo data (the band's own acceptance fixture), loaded once it is healthy
#   3. the public gateway on $PORT, which blocks the /_test/* control endpoints
# The demo data is reloaded every RESEED_HOURS hours so visitors always see a clean wallet.
set -euo pipefail
cd "$(dirname "$0")/.."

export APP_PORT="${APP_PORT:-18080}"
RESEED_HOURS="${RESEED_HOURS:-6}"

(cd stage-4 && PORT="$APP_PORT" exec python3 -m app.server) &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true' EXIT

python3 replit/seed_demo.py
(while sleep "$((RESEED_HOURS * 3600))"; do python3 replit/seed_demo.py || true; done) &

exec python3 replit/demo_gateway.py
