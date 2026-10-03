#!/usr/bin/env bash
# Bring one factory seat online as a Claude Code session joined to Band Desktop.
#
#   seats/start-seat.sh <seat> [extra directory ...]
#
# Run from the result repository root, one terminal per seat, Lead last. Extra directories
# (the specification folder, a checker's folder, a scratch folder for check outputs) are
# granted to the seat with --add-dir so reading them never prompts.
#
# The seat's model is read from the `Model:` line of mandates/<seat>.md, so the mandate is
# the single source of truth for what the seat runs. Permission mode `auto` approves
# routine actions and refuses risky ones instead of prompting, so an unattended seat never
# blocks on a dialog; `.claude/settings.json` adds explicit allow and deny rules on top.
set -euo pipefail

SEAT="${1:?usage: seats/start-seat.sh <lead|analyst|builder|designer|verifier> [extra dir ...]}"
shift
REPO="$(git rev-parse --show-toplevel)"
MANDATE="$REPO/mandates/$SEAT.md"
[ -f "$MANDATE" ] || { echo "no mandate at $MANDATE" >&2; exit 1; }

MODEL="$(sed -n 's/^Model:[[:space:]]*//p' "$MANDATE" | head -1)"
NAME="$(sed -n 's/^# //p' "$MANDATE" | head -1)"
HANDLE="$(echo "$SEAT" | tr '[:upper:]' '[:lower:]')"

ADD_DIRS=()
for dir in "$@"; do ADD_DIRS+=(--add-dir "$dir"); done

cd "$REPO"
exec claude --model "$MODEL" --permission-mode auto ${ADD_DIRS[@]+"${ADD_DIRS[@]}"} \
  "/jam Start a Band Desktop session as the seat named \"$NAME\" (handle @$HANDLE). \
Stay parked until the Lead adds you to a room. Your standing mandate is mandates/$SEAT.md and \
the shared rules are playbook/PROTOCOL.md: read both now, in full, and follow them for this \
whole session. The result repository is $REPO. After reading, wait for a message addressed \
to you before starting any work."
