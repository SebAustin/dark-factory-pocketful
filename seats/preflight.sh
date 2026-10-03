#!/usr/bin/env bash
# Check that the factory can run unattended, before you dispatch anything.
#
#   seats/preflight.sh [room id]
#
# Run from the result repository root. Every check here maps to a failure we hit while
# rehearsing: a dispatch into a room the seats were not in, an expired login, a Claude
# Code too old for the configured models, and tools missing from the seats' PATH.
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:$HOME/.docker/bin:/opt/homebrew/bin:$PATH"

ROOM="${1:-}"
REPO="$(git rev-parse --show-toplevel)"
SEAT_BIN="$REPO/seats/claude-seat.sh"
SEATS=(lead analyst builder designer verifier)
fail=0
ok()  { printf '  [ok]   %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "factory preflight: $REPO"

band preflight >/dev/null 2>&1 || band daemon status >/dev/null 2>&1 \
  && ok "Band daemon reachable" || bad "Band daemon not reachable (open Band Desktop)"

if "$SEAT_BIN" auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  ok "seat config directory signed in"
else
  bad 'seat config directory not signed in: CLAUDE_CONFIG_DIR="$HOME/.claude-factory" claude auth login'
fi

version="$("$SEAT_BIN" --version 2>/dev/null | awk '{print $1}')"
[ -n "$version" ] && ok "Claude Code $version (run 'claude update' if a model needs newer)" \
  || bad "Claude Code not runnable through seats/claude-seat.sh"

docker info >/dev/null 2>&1 && ok "Docker daemon running" || bad "Docker daemon not running"

for seat in "${SEATS[@]}"; do
  [ -f "$REPO/mandates/$seat.md" ] || { bad "missing mandates/$seat.md"; continue; }
  status="$(band sessions --session "factory-$seat" 2>/dev/null)"
  [ -n "$status" ] || { bad "seat $seat not created (seats/create-seats.sh)"; continue; }
  echo "$status" | grep -q "claude-seat.sh" && ok "seat $seat runs seats/claude-seat.sh" \
    || bad "seat $seat does not run seats/claude-seat.sh (re-run seats/create-seats.sh)"
  if [ -n "$ROOM" ]; then
    echo "$status" | grep -q "room=$ROOM" && ok "seat $seat bound to room $ROOM" \
      || bad "seat $seat is not in room $ROOM"
  fi
done

[ "$fail" -eq 0 ] && echo "ready" || echo "not ready: fix the [FAIL] rows, then re-run"
exit "$fail"
