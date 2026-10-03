#!/usr/bin/env bash
# Install this factory into a fresh, empty result repository.
#
#   ./bootstrap.sh /absolute/path/to/new/result
#
# Works from the factory source folder and from any clone of a repository the factory
# produced: it copies the factory files that sit next to it (mandates, protocol, skills,
# settings, seat launcher, docs, dispatch texts) and commits them as the initial state.
# Stage folders, reviews and run logs are left to the band.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:?usage: bootstrap.sh /absolute/path/to/new/result}"
FILES=(.claude .gitignore bootstrap.sh FACTORY.md README.md dispatch mandates playbook seats
       reviews/README.md runlog/README.md)

case "$TARGET" in
  /*) ;;
  *) echo "error: give an absolute path; seats resolve paths from their own sandbox" >&2; exit 1 ;;
esac
case "$TARGET" in
  *" "*) echo "error: the path must not contain spaces; agents and Docker mishandle them" >&2; exit 1 ;;
esac
if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  echo "error: $TARGET exists and is not empty; every submitted run needs a fresh repository" >&2
  exit 1
fi

mkdir -p "$TARGET"
git -C "$TARGET" init -q -b main
git -C "$TARGET" config user.name "Factory"
git -C "$TARGET" config user.email "factory@factory.local"

(cd "$SRC" && tar cf - "${FILES[@]}") | (cd "$TARGET" && tar xf -)

git -C "$TARGET" add -A
git -C "$TARGET" commit -q -m "chore: install factory (mandates, protocol, skills)"
echo "factory installed at $TARGET ($(git -C "$TARGET" rev-parse --short HEAD))"
