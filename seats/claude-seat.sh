#!/usr/bin/env bash
# The runtime executable every seat runs: Claude Code with a factory-only config directory.
#
# Seats never load the operator's personal ~/.claude (its hooks, plugins, MCP servers and
# permission "ask" rules). Each seat sees only this repository's .claude/settings.json and
# .claude/skills, so the factory behaves the same on every machine and no seat stops on a
# permission dialog that nobody is there to answer.
#
# One-time setup (signs the factory config directory in to Claude):
#   CLAUDE_CONFIG_DIR="$HOME/.claude-factory" claude auth login
set -euo pipefail

export CLAUDE_CONFIG_DIR="${FACTORY_CLAUDE_HOME:-$HOME/.claude-factory}"
# The stored login is looked up per user account; make sure the account name is set.
export USER="${USER:-$(id -un)}"
mkdir -p "$CLAUDE_CONFIG_DIR"

# The daemon starts seats with a minimal PATH; put the usual tool locations (docker, git,
# python, the band CLI) back so every seat finds the same tools.
export PATH="$HOME/.local/bin:/usr/local/bin:$HOME/.docker/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"

# The daemon that spawns seats may not inherit the operator's shell PATH.
CLAUDE_BIN="${CLAUDE_BIN:-}"
if [ -z "$CLAUDE_BIN" ]; then
  for candidate in "$(command -v claude 2>/dev/null || true)" "$HOME/.local/bin/claude" \
                   /opt/homebrew/bin/claude /usr/local/bin/claude; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLAUDE_BIN="$candidate"; break; fi
  done
fi
[ -n "$CLAUDE_BIN" ] || { echo "claude-seat: no claude executable found; set CLAUDE_BIN" >&2; exit 127; }

exec "$CLAUDE_BIN" "$@"
