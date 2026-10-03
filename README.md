# Pocketful, built by a Ledger-First Dark Factory

Entry for the **WeAreDevelopers x BAND: Dark Factory** hackathon, track **pocketful** (a
wallet and payments service). Team: Sébastien Henry.

Everything under `stage-N/` was written by five coding-agent seats working in one Band
Desktop room. The only human inputs were the four stage tasks in [`dispatch/`](dispatch/),
each sent once.

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | The factory: seats, flow, how to stand it up, design choices and their cost, how it catches bad work, measured time and spend |
| [`mandates/`](mandates/) | One standing instruction per seat (generic; no track detail) |
| [`playbook/PROTOCOL.md`](playbook/PROTOCOL.md) | Shared rules: packets, work items, gates, verdicts, repository discipline |
| [`.claude/skills/`](.claude/skills/) | Factory skills the seats use: `spec-ledger`, `slice-tdd`, `gate-review`, `diagnose`, `screen-craft` |
| [`seats/start-seat.sh`](seats/start-seat.sh) | Starts a seat as a Claude Code session joined to Band Desktop |
| [`dispatch/`](dispatch/) | The exact task text sent to the lead for each stage (the only human input) |
| [`reviews/`](reviews/) | The verifier's verdicts and screenshots, per stage |
| [`runlog/`](runlog/) | The lead's per-stage log: work items, owners, verdicts, rejections, gate tables, wall time |
| [`room.json`](room.json) | The Band room, downloaded unchanged (full session) |
| `stage-1/` … `stage-4/` | One complete service per stage; each has a `Dockerfile` and a `RUN.md` |

Inside each stage folder, `docs/ledger.md` is the requirements ledger, `docs/decisions/`
the decision records, and `acceptance/` the analyst's acceptance suite. The verifier's
verdicts and screenshots are in [`reviews/`](reviews/), outside the frozen stage folders.
[`bootstrap.sh`](bootstrap.sh) installs this factory into a new empty repository.

## Run a stage

Follow the stage folder's `RUN.md`. In short: build its `Dockerfile` and run the image with
`-e PORT=8080 -p 8080:8080`; it needs no network at run time.
