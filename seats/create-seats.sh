#!/usr/bin/env bash
# Create the five factory seats (or re-point existing ones at this repository) as Band-owned, headless Claude Code agents.
#
#   seats/create-seats.sh [--dry-run] [seat ...]        (default: all five seats)
#
# Run from the result repository root. Each seat:
#   - runs Claude Code as a runtime the Band daemon owns (no terminal to babysit);
#   - works in this repository and takes its model from its mandate's `Model:` line;
#   - has its mandate as live-linked owner instructions (edit the file, the seat follows);
#   - runs in permission mode `auto` (routine actions approved, risky ones refused, no
#     dialog ever blocks) and loads this repository's .claude/ settings and skills;
#   - loads only Band's own MCP relay (strict MCP config), not the operator's servers;
#   - runs Claude Code with a factory-only config directory (seats/claude-seat.sh).
#
# Requires Band Desktop (daemon running, `band` on PATH) and Claude Code signed in.
set -euo pipefail

DRY=()
if [ "${1:-}" = "--dry-run" ]; then DRY=(--dry-run); shift; fi
SEATS=("$@")
[ ${#SEATS[@]} -gt 0 ] || SEATS=(lead analyst builder designer verifier)

REPO="$(git rev-parse --show-toplevel)"
# Seats run Claude Code through seats/claude-seat.sh: a factory-only config directory, so
# the operator's personal hooks, plugins and permission "ask" rules never reach a seat.
SEAT_BIN="$REPO/seats/claude-seat.sh"
[ -x "$SEAT_BIN" ] || { echo "missing $SEAT_BIN" >&2; exit 1; }
"$SEAT_BIN" auth status 2>/dev/null | grep -q '"loggedIn": true' || {
  echo "the factory config directory is not signed in; run once:" >&2
  echo '  CLAUDE_CONFIG_DIR="$HOME/.claude-factory" claude auth login' >&2; exit 1; }

for seat in "${SEATS[@]}"; do
  mandate="$REPO/mandates/$seat.md"
  [ -f "$mandate" ] || { echo "no mandate at $mandate" >&2; exit 1; }
  name="$(sed -n 's/^# //p' "$mandate" | head -1)"
  model="$(sed -n 's/^Model:[[:space:]]*//p' "$mandate" | head -1)"
  instructions=(--instructions-file "$mandate")
  [ ${#DRY[@]} -eq 0 ] || instructions=()
  echo "== $name ($model)"
  if [ ${#DRY[@]} -eq 0 ] && [ -n "$(band sessions --session "factory-$seat" 2>/dev/null)" ]; then
    # The seat already exists: re-point it at this repository (fresh run, same identity).
    band runtime template set --session "factory-$seat" \
      --spawn-command "$SEAT_BIN" --spawn-cwd "$REPO" \
      --runtime-auth subscription --runtime-model "$model" \
      --claude-permission-mode auto --claude-context-mode local_config \
      --claude-strict-mcp-config
    band agent instructions set --session "factory-$seat" --instructions-file "$mandate"
    continue
  fi
  band agent create ${DRY[@]+"${DRY[@]}"} \
    --session "factory-$seat" \
    --name "$name" \
    --description "Factory seat: see mandates/$seat.md" \
    --cwd "$REPO" \
    --transport claude-code-cli \
    --spawn-command "$SEAT_BIN" \
    --runtime-auth subscription \
    --runtime-model "$model" \
    --claude-permission-mode auto \
    --claude-context-mode local_config \
    --claude-strict-mcp-config \
    ${instructions[@]+"${instructions[@]}"} \
    --json
done
