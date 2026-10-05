# Pocketful, built by a Ledger-First Dark Factory

Entry for the **WeAreDevelopers x BAND: Dark Factory** hackathon, track **pocketful** (a
wallet and payments service). Team: Sébastien Henry.

Everything under `stage-N/` was written by five coding-agent seats working in one Band
Desktop room. The only messages a human sent to the room were the four stage tasks in
[`dispatch/`](dispatch/), each sent once. Outside the room the operator took three
infrastructure actions, each listed in [`FACTORY.md`](FACTORY.md) section 8: re-attaching
the seat workers after a Band daemon restart, restarting Docker Desktop between stages 3
and 4, and restarting the lead's worker when stage 4 stalled.

**Where the run ended.** Stages 1 to 3 were each accepted by the band's own stage gate.
Every stage 4 item was accepted, but the stage 4 gate never ran: a verdict that never
reached the lead stalled the band (FACTORY.md section 8). Each stage folder claims its
stage on the event's shipped checks in isolated mode (147/147, 35/35, 6/6, 5/5).

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, flow, how to stand it up, design choices and their cost, how it catches bad work, measured time and spend |
| [`mandates/`](mandates/) | One standing instruction per seat (generic; no track detail) |
| [`playbook/PROTOCOL.md`](playbook/PROTOCOL.md) | Shared rules: packets, work items, gates, verdicts, repository discipline |
| [`.claude/skills/`](.claude/skills/) | Factory skills the seats use: `spec-ledger`, `slice-tdd`, `gate-review`, `diagnose`, `screen-craft` |
| [`seats/`](seats/) | Seat setup: `create-seats.sh` (Band-owned headless seats), `claude-seat.sh` (isolated Claude Code config), `preflight.sh`, `watchdog.sh`, `seat-usage.py` (token and cost per seat and stage), `start-seat.sh` (interactive alternative) |
| [`dispatch/`](dispatch/) | The exact task text sent to the lead for each stage (the only human input) |
| [`reviews/`](reviews/) | The verifier's verdicts and screenshots, per stage |
| [`runlog/`](runlog/) | The lead's per-stage log: work items, owners, verdicts, rejections, gate tables, wall time |
| [`room.json`](room.json) | The Band room, downloaded unchanged (full session). Band's export holds the most recent 4,000 messages, so it starts at the stage 2 carry-forward (2026-10-03 22:55Z); stage 1 is traced by [`runlog/stage1.md`](runlog/stage1.md), [`reviews/stage1/`](reviews/stage1/) and its commits |
| `stage-1/` … `stage-4/` | One complete service per stage; each has a `Dockerfile` and a `RUN.md` |

Inside each stage folder, `docs/ledger.md` is the requirements ledger, `docs/decisions/`
the decision records, and `acceptance/` the analyst's acceptance suite. The verifier's
verdicts and screenshots are in [`reviews/`](reviews/), outside the frozen stage folders.
[`bootstrap.sh`](bootstrap.sh) installs this factory into a new empty repository.

## Run a stage

Follow the stage folder's `RUN.md`. In short: build its `Dockerfile` and run the image with
`-e PORT=8080 -p 8080:8080`; it needs no network at run time.
