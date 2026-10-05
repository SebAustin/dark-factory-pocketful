#!/usr/bin/env bash
# Keep the seats' workers alive for the length of a run.
#
#   seats/watchdog.sh [interval seconds, default 60]
#
# A Band daemon restart (for example when Band Desktop updates its Claude Code plugin)
# stops every owned seat's worker mid-turn, and nothing brings them back: the run stalls
# with every seat waiting on another. This loop checks each seat and re-attaches any
# stopped worker. It is infrastructure only: it never posts in a room, so it cannot steer
# the band. Unsettled inbound messages are redelivered when a worker comes back.
set -uo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

INTERVAL="${1:-60}"
SEATS=(lead analyst builder designer verifier)

while true; do
  for seat in "${SEATS[@]}"; do
    state="$(band status --session "factory-$seat" 2>/dev/null | head -1)"
    case "$state" in
      *"running=true"*) ;;
      *)
        echo "$(date -u +%FT%TZ) seat $seat not running (${state:-no status}); re-attaching"
        band attach --session "factory-$seat" >/dev/null 2>&1 \
          && echo "$(date -u +%FT%TZ) seat $seat: $(band status --session "factory-$seat" 2>/dev/null | head -1)"
        ;;
    esac
  done
  sleep "$INTERVAL"
done
