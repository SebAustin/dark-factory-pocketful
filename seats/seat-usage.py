#!/usr/bin/env python3
"""Token usage per seat and per stage window, read from the seats' own transcripts.

Band's usage scanner reads ~/.claude only; the seats run with CLAUDE_CONFIG_DIR=~/.claude-factory,
so their sessions never reach `band usage`. This reads those transcripts directly.

  seat-usage.py <projects dir> <seat=session-uuid>... --window name=START,END ...

Each assistant message is counted once (deduplicated by message id; Claude Code writes one
line per content block, each repeating the same usage). Subagent transcripts in the
<session-uuid>/ folder are included under the same seat.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def parse_args(argv):
    root, seats, windows = Path(argv[0]), {}, []
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--window":
            name, span = rest[i + 1].split("=", 1)
            start, end = span.split(",")
            windows.append((name, datetime.fromisoformat(start), datetime.fromisoformat(end)))
            i += 2
            continue
        seat, uuid = rest[i].split("=", 1)
        seats[seat] = uuid
        i += 1
    return root, seats, windows


def transcript_files(root, uuid):
    main = root / f"{uuid}.jsonl"
    files = [main] if main.exists() else []
    sub = root / uuid
    if sub.is_dir():
        files.extend(sorted(sub.rglob("*.jsonl")))
    return files


def messages(files):
    seen = set()
    for path in files:
        with path.open(errors="ignore") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = row.get("message") or {}
                usage = msg.get("usage")
                if not usage or msg.get("id") in seen:
                    continue
                seen.add(msg.get("id"))
                stamp = row.get("timestamp")
                if not stamp:
                    continue
                yield datetime.fromisoformat(stamp.replace("Z", "+00:00")), msg.get("model", "?"), usage


def window_of(stamp, windows):
    for name, start, end in windows:
        if start <= stamp < end:
            return name
    return "other"


def main():
    root, seats, windows = parse_args(sys.argv[1:])
    totals = defaultdict(lambda: defaultdict(int))
    for seat, uuid in seats.items():
        for stamp, model, usage in messages(transcript_files(root, uuid)):
            key = (seat, window_of(stamp, windows), model)
            totals[key]["messages"] += 1
            for field in FIELDS:
                totals[key][field] += usage.get(field) or 0
    print(json.dumps([{"seat": s, "window": w, "model": m, **dict(v)}
                      for (s, w, m), v in sorted(totals.items())], indent=1))


if __name__ == "__main__":
    main()
