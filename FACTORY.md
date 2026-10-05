# FACTORY.md: Ledger-First Dark Factory

A five-seat software factory for Band Desktop. You give the **Lead** one task; the band
reads the specification into a numbered requirements ledger, plans against it, builds in
parallel lanes, and lets an independent **Verifier** with a veto accept or reject every
revision against gates it runs itself. Between the dispatch and the final report the band
runs unattended.

Everything here is generic. Nothing in `mandates/`, `playbook/` or `.claude/skills/`
names a product, an endpoint, a field or an error code; the task pasted into the room
(see `dispatch/`) carries all of that. We pointed it at a wallet service; you could point
it at a ticketing system, an inventory service or a scheduler without changing a line.

---

## 1. The band

| Seat | Harness | Model | Owns | Leaves to others |
|---|---|---|---|---|
| **Lead** | Claude Code | claude-opus-5-5 | stage plan, work items, routing, gates, run state, run log, final report | product code and tests |
| **Analyst** | Claude Code | claude-opus-5-5 | requirements ledger, glossary, acceptance suite, plan critique, diagnosis | product code |
| **Builder** | Claude Code | claude-opus-5-5 | the core: domain logic, storage, public interface, build, run instructions | accepting its own work |
| **Designer** | Claude Code | claude-sonnet-5-5 | everything user facing; core items when a stage has no screens | accepting its own work |
| **Verifier** | Claude Code | claude-opus-5-5 | independent checks, two-axis review, the verdict | fixing what it judges |

Mandates: [`mandates/`](mandates/). Shared rules: [`playbook/PROTOCOL.md`](playbook/PROTOCOL.md).
Factory skills, loaded by Claude Code from the repository: [`.claude/skills/`](.claude/skills/)
(`spec-ledger`, `slice-tdd`, `gate-review`, `diagnose`, `screen-craft`).

```mermaid
flowchart LR
  H([Human task]) --> L[Lead]
  L -- spec packet --> A[Analyst]
  L -- spec packet --> B[Builder]
  A -- ledger + top risks --> L
  B -- plan --> L
  L -- plan --> A
  A -- PASS / REVISE --> L
  L -- work items --> B & D[Designer] & A
  B -- revision + evidence --> V[Verifier]
  D -- revision + screenshots --> V
  A -- acceptance suite --> V
  V -- VERDICT REJECT + repro --> B & D
  V -- VERDICT ACCEPT --> L
  L -- stage gate packet --> V
  L --> R([Final report])
```

## 2. How a stage runs

1. **Carry forward.** The builder copies the last accepted stage folder, deletes nested
   version control, and commits the copy unchanged. Accepted folders are frozen.
2. **Ledger first** (Analyst, `spec-ledger`). Every constraining sentence becomes a row
   `R<stage>.<n>` with its verbatim quote and how it will be proven. The analyst hunts what
   a quick reading misses: boundaries, error order, repeated and simultaneous requests,
   time, upgrades of existing state. Judged checks are mostly hidden but all written in the
   specification, so the ledger's completeness is the stage's ceiling.
3. **Plan and critique.** The builder plans modules and where each invariant is enforced
   (one place each); the analyst scores it against the ledger, PASS or REVISE, two rounds.
4. **Parallel lanes.** The lead cuts work items with one owner, owned paths, requirement
   ids and DONE WHEN commands. The analyst writes the acceptance suite *from the ledger*;
   the builder and the designer build their items test first (`slice-tdd`,
   `screen-craft`). When a stage has no screens the designer builds core items, so the
   work stays distributed.
5. **Item review.** Each finished item goes to the verifier as a self-contained packet; the
   verifier checks it out into its own worktree, re-runs the DONE WHEN commands and the
   item's tests, reviews the diff, and answers ACCEPT or REJECT with reproducing commands.
6. **Stage gate.** On one revision the verifier runs G1 to G8 (PROTOCOL section 4): ledger
   coverage, plan, acceptance suite, every earlier suite (the chain), any checker the task
   supplies, an invariant stress run, a two-axis review of the whole stage, and every
   user-facing state at the required viewports.
7. **Record.** The lead keeps `runlog/state.md` (durable state that survives context
   compaction) and writes `runlog/stage<N>.md`: items, owners, times, verdicts, what each
   rejection caught, the gate table and wall time. Verdicts live in `reviews/`.

## 3. Stand it up (about 30 minutes)

**Prerequisites:** macOS, Linux or Windows (WSL2); Git; Docker running; Python 3.12+;
Claude Code signed in (we used a subscription); a [Band](https://app.band.ai) account;
[Band Desktop](https://docs.band.ai/band-desktop) installed with its readiness checks green
(the `band` CLI on the PATH and the `band-peer` Claude Code plugin installed). The plugin is
what wakes a seat: an @mention in the room arrives in that seat's Claude Code session as a
new turn, and `/jam` registers a session as a Band agent.

1. **Install the factory into a fresh repository** (from a clone of this repository):
   ```sh
   ./bootstrap.sh /absolute/path/without/spaces/result
   cd /absolute/path/without/spaces/result
   ```
2. **Create the five seats** as Band-owned, headless Claude Code agents (once per
   machine; re-run to re-point them at a new repository):
   ```sh
   seats/create-seats.sh --dry-run lead   # probe the runtime first, creates nothing
   seats/create-seats.sh                  # create Lead, Analyst, Builder, Designer, Verifier
   ```
   Before the first run, sign the factory's own Claude config directory in, once:
   `CLAUDE_CONFIG_DIR="$HOME/.claude-factory" claude auth login`. Seats run Claude Code
   through `seats/claude-seat.sh`, which points it at that directory, so a seat never
   inherits the operator's personal hooks, plugins, MCP servers or permission rules (our
   rehearsal showed why: personal `ask` rules stopped every container command on a
   permission dialog). The wrapper also restores a full PATH, because the daemon starts
   seats with a minimal one and the seats could not find `docker`.

   The Band daemon owns and supervises each seat's Claude Code process (no terminal to keep
   open). Each seat works in the repository, takes its model from its mandate's `Model:`
   line, has its mandate as **live-linked owner instructions**, runs in permission mode
   `auto` (routine actions approved, risky ones refused, nothing waits on a dialog), loads
   the repository's `.claude/` settings and skills, and loads only Band's own MCP relay
   (`--claude-strict-mcp-config`), not the operator's MCP servers.
2b. **Pre-flight, every time before a dispatch** (each item cost us a failed first turn
   or a stall; `seats/preflight.sh <room>` checks most of them):
   - `CLAUDE_CONFIG_DIR="$HOME/.claude-factory" claude auth status` shows
     `"loggedIn": true`; an expired session fails the first turn with an authentication
     error.
   - `claude --version` is new enough for the models in the mandates (`claude update`),
     then `band restart` any seat runtime started on the old binary.
   - Every seat is a participant of the room **and** bound to it (`band sessions --all`
     shows the room id per seat). A message in a room the seats are not in goes nowhere,
     silently.
   - The seats are in **no other room** with unfinished work: reviving a seat revives every
     room it is bound to (we restarted a finished rehearsal by accident).
   - Docker is running (`docker info`). Docker Desktop stopped overnight between two of
     our stages.
2c. **Keep the workers alive** for the length of the run: `seats/watchdog.sh &`. A Band
   daemon restart (Band Desktop updating its Claude Code plugin did this mid-run) stops
   every owned worker and nothing restarts them; the watchdog re-attaches stopped workers
   and never posts in the room. To restart one seat in one room only, use
   `band restart --session factory-<seat> --host-session default-<room id>`, not
   `band attach`, which revives all of that seat's rooms.
3. **Create the room** in Band Desktop with a fresh name and add the five seats. (The lead's
   mandate also re-checks membership and adds any missing seat itself.)
4. **Smoke test.** Ask the lead in the room to ping each seat by handle and confirm every
   seat replied. Seats see only messages addressed to them, so this proves routing.
5. **Rehearse** on a small problem end to end (we used the event's practice track).
6. **Run.** In a *fresh* room and a *fresh* repository, paste one stage task per stage
   (ours are in [`dispatch/`](dispatch/)). Send nothing else until the lead's final report.

*Alternative seat setup:* interactive Claude Code sessions joined with the `band-peer`
plugin, one terminal per seat: `seats/start-seat.sh <seat> [extra dirs]`. Docker Sandboxes
(Band Desktop: Settings, Experiments) add isolation for unattended runs.

*Setup gotchas we hit:* the daemon may not inherit your shell's PATH, so the script pins
the `claude` executable path; `bare` context mode cannot use a Claude subscription; and with
the operator's own MCP servers loaded, Band's relay connected too slowly for the runtime
probe, hence strict MCP config.

## 4. Design choices, and what they cost

| Choice | Why | Cost |
|---|---|---|
| **Ledger before code** | The judged suite is mostly hidden but fully written in the spec. A row per sentence turns "read carefully" into an artefact with a completeness criterion that every later step cites. | A serial step at the start of each stage. |
| **Tests by a seat that does not build** | A builder testing its own work tests what it built, not what was asked. The analyst writes tests from the ledger. | Some overlap between builder unit tests and analyst acceptance tests. |
| **Verifier with a veto that never fixes** | Separating judgement from authorship makes "review changed something" real and keeps every defect visible in the room. | Every defect costs a round trip, bounded by budgets. |
| **Light item review, full stage gate** | Full gates on every item would make the verifier the queue in front of three lanes. | Some defects surface only at the stage gate. |
| **Self-contained packets** | Band seats see only messages addressed to them; a pointer is an empty handoff. Fixed headings make omissions visible. | Long messages; specifications are pasted in numbered parts. |
| **Every turn ends with a message** | Seats wake only on messages; one silent turn stalls the factory. | Some status chatter. |
| **One shared tree, path ownership, verifier worktrees** | Seats share a repository so history is one story; the verifier judges an exact revision in its own worktree, never the tree others are editing. | Commits must name their paths; occasional index lock retries. |
| **Per-seat commit authors** | History shows who did what and traces each commit to the packet it answers. | None. |
| **Durable lead state on disk** | The lead's context fills over a multi-hour run; `runlog/state.md` survives compaction. | One file write per lifecycle change. |
| **Opus on judgement seats, Sonnet on screens** | Ledger, build and verdict errors are expensive; screen work is high volume and well specified. | Opus seats dominate spend (section 7). |

## 5. How the factory catches and recovers from bad work

- **Independent re-execution.** The verifier rebuilds from scratch in its own worktree and
  re-runs every command; reported output is evidence to compare, not to trust.
- **The chain gate.** A stage folder must pass every earlier stage's acceptance suite, so
  a regression introduced while extending is caught before acceptance.
- **Anti-overfitting.** Supplied checkers are black boxes: run them, read their output,
  leave their test sources unread. The verifier's spec axis rejects code that recognises
  particular test inputs; the builder fixes rules for every input.
- **Invariant stress.** Simultaneous and repeated writes, then a read-back of every
  invariant, several times over, because a race passes once.
- **Budgets.** Three rejections per item, then the lead re-plans (split, re-assign, or
  diagnose). Three failed stage gates, or a gate red for reasons outside the band, and the
  lead records the blocker and reports the best revision instead of looping.
- **Diagnosis loop.** A failure that returns twice goes to the analyst (`diagnose`): a red
  loop first, then minimise, rank falsifiable hypotheses, and hand the owner a proven cause.
- **Liveness.** Every turn ends with a message; a silent seat gets a ping, then its packet
  again, then its item moves to another owner.
- **History that only grows.** Settings deny amend, rebase, hard reset, stash, clean and
  force push; at each stage gate the verifier proves the last accepted revision is an
  ancestor of the new one.

### Bad results it caught in the submitted run

Every rejection below was found by a seat, with a reproducing command, and fixed by a new
commit from the owner; the verdicts are in [`reviews/`](reviews/), the reasons in
[`runlog/`](runlog/). Item rejections across the run: 12; stage gate failures: 2.

| Stage | Verdict | What it caught |
|---|---|---|
| 1 | REJECT `0fa1f0b` (S1.1) | HEAD/OPTIONS returned a 501 HTML page and a malformed request line a stdlib HTML 400; the spec requires a JSON error envelope on every 4xx/5xx and no 5xx. Root cause and curl repro in the verdict. |
| 1 | REJECT `7e7c5c1` (S1.3) | The activity feed sorted RFC 3339 timestamps as strings: `19:00+02:00` (17:00Z) ordered after `18:30+00:00`. The verifier built a two-payment mixed-offset fixture. |
| 1 | REJECT `52bf3ed` (S1.7) | A legal zero-share split made an unchanged export fail re-import with 422, against "must accept an unchanged export produced by this service". Found by combining two features; the fix became a round trip after every kind of write. |
| 1 | REJECT `5ff293a` (S1.13) | A concurrency fix serialised password hashing: in an A/B under the same load, calls over the 5 s limit went from 0/0/0 to 9/3/14 across three runs. A measured regression, not a test failure. |
| 2 | REJECT `0fa1361` (S2.U2+U3) | The signed-in header overflowed between 641 and about 1030 px, with "Log out" drawn over the user name at 1024. The task only asked for 375 px and desktop; the verifier added 768 and 1024 on its own and kept them for every later review. |
| 2 | REJECT `74d83a5` (S2.U10) | After editing a field, the click on the submit button was lost: a `change` handler cleared a notice above the button, the button moved before mouseup. Found by the analyst's acceptance test, diagnosed by the verifier with an A/B repro (1 request instead of 2). |
| 2 | REJECT `c6a8996` (S2.U11) | A refused payment's error rendered entirely under the fixed phone tab bar (0 px visible at 390 × 844). The verifier noted that no DOM-level check could see it ("the element is visible"); it was caught only by judging the screenshot. |
| 2 | Gate REJECT `6c295d6` | `stage-2/RUN.md` was still the stage 1 copy: its repository-root command built and started stage 1. |
| 3 | REJECT `fe6ff39` (S3.3) | Every statement read stored its whole window until reset: 5,500 reads gave a 69.3 MB export (over the import cap, so the service refused its own export) and 382 MiB of memory. The fix stores a constant-size recipe: 0.4 MB, 20.1 MiB. |
| 4 | REJECT `d1ffc66`, `2793971`, `1067a3f` (S4.3) | Three successive growth findings on exported snapshots: 378.9 MB in 13.2 s, then states retained per import (78 MB), then distinct states not sharing their index (26 → 76 MB). Each came with its own measuring tool; the fourth revision `81f3bbf` was accepted. |

Also caught without a rejection: a cross-stage conflict (stage 1 "import removes all
previous credentials" against stage 2 "a browser signed in before the upgrade must remain
signed in"), settled by the analyst's decision record and a lead ruling before any code
was written; and the designer's reference model, which proved its own checker by planting
divergences before trusting a clean result.

## 6. Keeping the factory generic

`mandates/` describe roles, handoffs and rejection criteria only, and contain no
identifier-shaped tokens (no paths starting with a slash, no snake or kebab case names),
so the event's vocabulary scan has nothing to match; `harness check` passes against both
tracks' lists. Track detail lives only in the task pasted into the room. Our test: hand
these mandates to a team building something else; every sentence still applies.

## 7. Measured cost and time

Measured on the submitted run. Wall time runs from the dispatch message to the stage
acceptance (room log timestamps, cross-checked with `runlog/`). Model usage comes from
each seat's own Claude Code transcripts, read by [`seats/seat-usage.py`](seats/seat-usage.py)
(one transcript per seat, each model call counted once, split by stage window). Cost is
the API list-price equivalent (Claude Opus 5.5: $4 input, $5 cache write, $0.20 cache
read, $20 output per million tokens; Claude Sonnet 5.5: $2, $2.50, $0.20, $10; cache
writes priced at the 5-minute rate). The seats actually ran on a Claude subscription.

| Stage | Wall time | Work items | Item rejections | Gate failures | Model calls | Cache read / cache write / output tokens | Equivalent API cost |
|---|---|---|---|---|---|---|---|
| 1 | 1 h 29 min (incl. a 16 min infrastructure stall) | 17 | 4 | 0 | 614 | 117.0 M / 1.43 M / 0.64 M | $40.91 |
| 2 | 2 h 15 min | 18 | 4 | 1 | 612 | 268.7 M / 1.19 M / 0.67 M | $71.02 |
| 3 | 1 h 14 min | 8 | 1 | 1 | 402 | 257.5 M / 0.86 M / 0.58 M | $65.18 |
| 4 | 1 h 25 min to the last item accept; **no gate** (section 8) | 12 | 3 | – | 308 | 207.7 M / 4.14 M / 0.41 M | $67.32 |
| **Run** | **6 h 23 min** of band time | **55** | **12** | **2** | **1,936** | **850.9 M / 7.62 M / 2.30 M** | **$244.44** |

Uncached input was under 4,000 tokens in total: almost everything a seat reads comes from
the prompt cache, which is why cache reads dominate the volume but not the bill.

| Seat | Model | Model calls | Output tokens | Equivalent API cost | Share |
|---|---|---|---|---|---|
| Lead | Opus 5.5 | 389 | 0.25 M | $35.12 | 14 % |
| Analyst | Opus 5.5 | 258 | 0.46 M | $39.30 | 16 % |
| Builder | Opus 5.5 | 405 | 0.54 M | $56.78 | 23 % |
| Designer | Sonnet 5.5 | 370 | 0.57 M | $44.92 | 18 % |
| Verifier | Opus 5.5 | 514 | 0.48 M | $68.31 | 28 % |

The verifier is the most expensive seat: it rebuilds and re-runs everything it judges, so
it reads more than anyone (201 M cache-read tokens). That is the price of independent
verification, and the rejections in section 5 are what it bought. Commits by seat: Lead 94,
Verifier 51, Builder 48, Designer 32, Analyst 19.

The rehearsal on the practice track cost a further $45.56 (as attributed by Band, before
the seats were isolated).

After each stage we ran the event checker ourselves, in isolated mode, outside the band.
Every stage claimed: 147/147, 35/35, 6/6 and 5/5 shipped checks for stages 1 to 4 (stage 4
on the shipped checks only, since its stage gate never ran).

## 8. What we tried that did not work

Design review before the first run (an independent plan critic and an adversarial
genericness review) removed these from an earlier draft:

- **A verifier that required a clean shared working tree**: with three lanes editing, the
  tree is never clean, so it would have waited forever. Replaced by per-revision worktrees.
- **Unbounded waits**: "wait for the final part", "ping a seat that has gone quiet" with no
  clock. Replaced by the end-every-turn-with-a-message rule and explicit budgets.
- **Full gates on every item**: would have made the verifier the bottleneck.
- **A designer idle in stages without screens**: one builder would have carried nearly all
  the code. The designer now takes core items.
- **Mandate wording that echoed the event's runtime table and UI rules**: generic in
  vocabulary but specific in shape; rewritten as "every constraint the specification
  states".

Rehearsal setup failures (each silent or a single error line, none caught by the seats
themselves, all now in the pre-flight list in section 3):

- **Dispatch into a room the seats were not in.** Nothing happened for an hour: no error,
  no log line. Fixed by creating the room with all seats and verifying their bindings.
- **Expired CLI login.** The first turn failed on authentication.
- **CLI older than the model required.** The first turn failed with an API error naming
  the minimum version.
- **Operator config leaking into seats.** Seats inherited the operator's personal Claude
  config, whose `ask` rules made every container command wait on a permission dialog,
  posted to the room with a mention of the human. The lead kept the run moving by
  approving or denying each request in the room (it correctly denied one that would have
  killed other seats' servers), but the right fix was isolation: seats now run with a
  factory-only config directory (`seats/claude-seat.sh`).
- **Minimal PATH for daemon-started seats.** Seats could not find `docker`; the lead
  diagnosed it and broadcast a workaround. The wrapper now restores the PATH.

What went wrong in the submitted run, in the order it happened. Operator actions are
listed in full: none of them was a message in the room.

- **A daemon restart stopped every seat (stage 1).** Band Desktop updated its Claude Code
  plugin mid-run; the daemon restarted, but the five owned workers stayed stopped. One seat
  was cancelled mid-turn and every other seat believed someone else was working: 16
  minutes with no commit or message. *Operator action:* re-attached each seat's worker
  (no message); unsettled messages were redelivered and the run resumed. *Fix:*
  `seats/watchdog.sh`.
- **Reviving a seat revives every room it is in.** That re-attach also woke the rehearsal
  room, whose band quietly finished its last two practice stages in parallel with the
  judged run (separate repository, no cross-contamination, but double the quota and a port
  range collision risk). *Fix:* the pre-flight item on old rooms, and single-room
  `band restart --host-session`.
- **Stale run instructions, twice (stages 2 and 3).** Each stage folder started as a copy,
  and its `RUN.md` still described, and built, the previous stage. The verifier failed the
  gate both times; the second time the lead named the cause itself ("no work item covered
  `RUN.md` after the carry-forward copy") and, for stage 4, made `RUN.md` part of the
  carry-forward item. The lesson lived in one seat's context; it is now in PROTOCOL
  section 6.
- **Docker Desktop stopped overnight** between stages 3 and 4. *Operator action:*
  restarted it before dispatching stage 4. *Fix:* a pre-flight item.
- **Stage 4 ended without a stage gate.** Every stage 4 item was accepted, but the
  verifier sent its last three S4.3 verdicts to the builder only. It typed the lead's
  handle into the text, which in Band reaches nobody; the builder chose not to reply to
  the final ACCEPT. The lead, idle since its last message, never learned that the stage
  was ready, and every seat waited: the run stalled with stage 4 complete and unjudged. The
  same slip meant the item's retry budget was never enforced (four attempts instead of
  three). *Operator action (with the team's approval):* restarted the lead's worker in that
  one room, with no message. It resumed its session but, with nothing addressed to it,
  took no turn; we left the run there rather than send a nudge. *Fix:* PROTOCOL sections 0
  and 5 (real mentions; owners forward every verdict to the lead; the budget is counted
  from the verdict files) and the `gate-review` skill.
- **Our cost meter could not see the seats.** Band's usage report reads Claude Code's
  default config directory; isolated seats write their transcripts elsewhere, so the judged
  room showed no cost at all. *Fix:* `seats/seat-usage.py` reads the seats' own
  transcripts (section 7).

## 9. Limitations

- Seats share one machine; port ranges and name prefixes per seat prevent collisions only
  if seats follow them.
- Opus-heavy seats are the main cost; a cheaper configuration (Sonnet builder) is untested.
- Permission mode `auto` refuses actions it judges risky; a refused action is reported, not
  retried with broader rights.
- Liveness depends on messages. A seat that is not addressed never wakes, so one missing
  mention can idle the whole band; nothing inside the room notices an idle band.

## 10. Changes made after the run

These were written after the submitted run ended and were **not** in effect during it.
They are in a separate commit so the factory that ran is still in the history.

- PROTOCOL section 0: a message reaches only the seats in the mention list.
- PROTOCOL section 5: every verdict reaches the lead (owners forward any that does not);
  the item budget is counted from the verdict files.
- PROTOCOL section 6: the carry-forward item rewrites the run instructions.
- `gate-review` skill: send the verdict with both owner and lead in the mention list.
- `seats/seat-usage.py` and the new pre-flight steps in section 3.
- `seats/watchdog.sh`: written during stage 1 after the daemon restart and run by the
  operator, outside the room, for stages 2 to 4; added to the repository now.

The seats never saw these files during the run: only the mandates, playbook and skills
installed at the start (commit `a01ead4`) were in their repository.

## Credits

Factory skills adapt ideas from Matt Pocock's skills (`tdd`, `diagnosing-bugs`,
`code-review`, `domain-modeling`, `writing-for-agents`; MIT licence) and from a
plan-critic / solution-verifier agency loop.
