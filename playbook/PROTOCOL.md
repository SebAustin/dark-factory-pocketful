# Factory protocol

The shared rules every seat follows. Mandates say *who* does what; this file says *how*
work moves between seats. If a mandate and this file disagree, the mandate wins for that
seat and the seat reports the disagreement to the lead.

## 0. The run

A **run** is one human task dispatched to the lead. From dispatch to the lead's final
report the band runs unattended: every question is answered inside the band, in this
order:

1. The task text and the specification it carries.
2. Evidence already in the repository (earlier stage folders, decision records).
3. The most conservative reading: the one that keeps every stated invariant and rejects
   input rather than guessing at it.
4. A decision record (section 8) so the choice is visible and reversible.

A seat that cannot proceed tells the lead what blocks it and what it has already proven.
The lead records the blocker in the run log and in the final report.

**Every turn ends with a message.** A seat is woken only by a message addressed to it, so
a seat that finishes a turn silently stops the factory. Every turn ends with a message to
the lead or to the next owner: a packet, a verdict, a status, or a blocker.

**Address with a real mention.** A message reaches only the seats named in the platform's
mention field. A handle typed into the text (for example a line ending in a handle) wakes
nobody. Before sending, check that every seat that must act next is in the mention list.

## 1. Seats and ownership

| Seat | Handle | Owns | Leaves to others |
|---|---|---|---|
| Lead | @lead | the stage plan, work items, routing, gates, run state, run log, final report | product code and tests |
| Analyst | @analyst | the requirements ledger, the glossary, the acceptance suite, plan critique, diagnosis | product code |
| Builder | @builder | the core: domain logic, storage, public interface, build, run instructions | accepting its own work |
| Designer | @designer | everything user facing: layout, states, styling, accessibility, client code; core work items when a stage has nothing user facing | accepting its own work |
| Verifier | @verifier | the verdict: independent checks, review, accept or reject | fixing what it judges (owners fix) |

These five seats are the whole band; seats address each other only by these handles. If
the human configured different seat names, those names replace these everywhere.

Ownership is by **path**, written in each work item. One file has one owner per work
item. A seat that needs a change in a path it does not own asks the owner through a packet.

## 2. Visibility: every handoff is a packet

Each seat sees only messages that address it by handle. A seat cannot read the room, the
task the human sent, another seat's messages, or a message id. Therefore every handoff is a
**packet** that carries everything the receiver needs, pasted in full.

A packet has these headings, in this order:

```
PACKET <stage>.<item> <short title>          (from @sender to @receiver)
GOAL         one sentence: what is true when this item is done
CONTEXT      repository path (absolute), stage folder, base revision, owned paths
REQUIREMENTS the requirement ids in scope, each with its verbatim specification quote
CONSTRAINTS  runtime limits, invariants, things that must stay unchanged
DONE WHEN    the exact commands to run and the result each must show
EVIDENCE     (on return) revision, commands run, their summarised output, open risks
```

A packet longer than one message is sent as numbered parts `PART 1/3` … `PART 3/3 (FINAL)`.
The receiver starts once the final part arrives; if a part is missing, it replies to the
sender naming the missing part number.

A receiver that finds a heading missing replies to the sender naming it, and works only
from content it was given.

Files in the repository (the ledger, decision records, earlier stage folders) are shared
memory every seat may read. A packet still pastes the requirements its receiver must act
on, so the handoff is complete on its own.

## 3. Work items

The lead splits each stage into work items small enough that one seat finishes one in a
single sitting: one behaviour, one seam, one owner. Each item has an id `S<stage>.<n>`,
an owner, the owned paths, the requirement ids it satisfies, and its DONE WHEN commands.

Lifecycle: `planned → assigned → built → in review → accepted`, or `→ rejected → assigned`.
The lead mirrors the lifecycle on the room's task board when the board is available, and
always in the run state file (section 9).

**Parallel lanes.** After the ledger exists, three lanes run at once: the analyst writes
acceptance tests, the builder and the designer each implement their own items. When a
stage has nothing user facing, the designer takes core work items with their own paths,
exactly like a second builder. The verifier reviews whatever reaches it.

## 4. Gates

**Item review** (every work item): the verifier re-runs the packet's DONE WHEN commands and
the tests for that item's requirements against a fresh checkout, and reviews the diff on
both axes. It is quick on purpose, so review never becomes the queue.

**Stage gate** (once per stage, on one revision): every gate below, run by the verifier.

| Gate | Question | Evidence |
|---|---|---|
| G1 Ledger | Is every constraining sentence of the specification a numbered requirement with a test or a stated reason it cannot be tested? | the ledger's coverage table has no blank rows |
| G2 Plan | Did the analyst PASS the plan, or did the lead record a decision after two rounds? | the PASS message or the decision record |
| G3 Acceptance | Does this stage's acceptance suite pass against the artifact, started per its run instructions? | command and pass count |
| G4 Chain | Do the earlier stages' acceptance suites, as carried into this stage folder, still pass against it? | command and pass count per suite |
| G5 Supplied checker | Does every checker the task supplies pass, run exactly as the task specifies? | the checker's final lines |
| G6 Invariants | Do the stated invariants hold under simultaneous and repeated writes? | the stress command and its result |
| G7 Review | Does the two axis review (standards and spec) of the whole stage diff find nothing blocking? | the verdict |
| G8 User facing | Where the stage has screens: every specified state renders at each required viewport with a clean console | screenshots and the list of states checked |

For the stage gate the lead sends the verifier the complete stage specification, pasted,
and the ledger's path.

## 5. Verdicts and budgets

The verifier answers every review with exactly one verdict:

```
VERDICT ACCEPT <revision>      or      VERDICT REJECT <revision>
GATES    each gate green, red, or not applicable, with the command that decided it
FINDINGS numbered; each names the requirement id, the observed behaviour, the expected
         behaviour with its specification quote, and a command that reproduces it
NEXT     who acts next and on which findings
```

A rejection names behaviour. A finding without a reproducing command or a specification
quote is a note, and notes never block.

**Every verdict reaches the lead.** The verifier sends each verdict to the owner and the
lead, both as mentions. An owner who receives a verdict that does not also mention the
lead forwards it to the lead in the same turn, ACCEPT included: the lead starts the stage
gate only when it knows the last item is accepted, and nothing else tells it.

**Item budget.** A work item may be rejected three times. On the fourth failure the lead
re-plans: split the item, move it to another owner, or send it to the analyst for
diagnosis. A re-planned item gets a new id and a fresh budget. The count comes from the
verdict files in the reviews folder, not from memory; an owner holding a third rejection
tells the lead before attempting a fourth.

**Stage budget.** A stage gate may fail three times. After the third failure, or when the
same gate stays red for reasons outside the band's control (tooling, infrastructure), the
lead records the blocker with evidence, reports the best revision reached, and ends the
run.

## 6. Repository discipline (one shared working tree)

All seats share one working tree, so every seat follows these rules:

- **Commit only your own paths**: `git add -- <your paths>` then
  `git -c user.name="<Seat>" -c user.email="<seat>@factory.local" commit -m "<msg>" -- <your paths>`.
  If the index is locked by another seat, wait a few seconds and retry.
- **Leave other seats' files alone**: no stash, clean, checkout or restore of paths you do
  not own. To look at an older revision, use a separate worktree:
  `git worktree add --detach <scratch folder>/<revision> <revision>`, and remove it after.
- **History only grows**: no amend, rebase, squash, hard reset or force push. A mistake is
  fixed by a new commit. At every stage gate the verifier confirms the last accepted
  revision is an ancestor of the new one (`git merge-base --is-ancestor`).
- **Commit messages**: `<type>(S<stage>.<n>): <what changed>`, types feat, fix, test,
  docs, chore, refactor. The body names the packet the commit answers.
- **Stage folders**: one per stage, each a complete product. A new stage starts by copying
  the last accepted stage folder, deleting any nested version control directory in the
  copy, and committing the copy unchanged; only then is it extended. An accepted stage
  folder is frozen.
- **Run instructions move with the stage.** The carry-forward item also rewrites the
  copy's run instructions for the new stage (title, every build and start command, what
  the artifact now serves, tool paths), and the verifier reviews them as part of that item.
  A copied file that still names the previous stage builds the wrong product.
- Report the full revision hash of every commit you hand off.
- Credentials stay out of the repository.

## 7. Shared machine

- **Ports and names.** Each seat starts artifacts only on its own ports and with its own
  container or process name prefix: analyst 18100 to 18199, builder 18200 to 18299,
  designer 18300 to 18399, verifier 18400 to 18499; prefix = the seat's handle. Stop what
  you started when you are done.
- **Target address.** Acceptance suites read the address of the artifact under test from
  the environment variable `TARGET_URL`, so any seat can point them anywhere.
- **Long commands.** Anything that may run longer than a few minutes (image builds,
  supplied checkers, stress runs) runs in the background with output to a log file under a
  scratch folder; the seat polls the log until it finishes. A command that hits a tool time
  limit has not failed; it is still running.
- **Checkers are black boxes.** Any checker the task supplies is run and its output read;
  its test sources stay unread, so the product is built to the specification and never to
  a particular check.

## 8. Decision records

When a seat makes a choice the specification leaves open, it writes a short decision
record in the stage folder under `docs/decisions/`: the question, the options, the choice,
and the specification text that constrained it. Later stages read these before changing
behaviour.

## 9. Run state and run log

- `runlog/state.md` is the lead's durable memory: current stage, every work item with its
  owner, lifecycle state and last revision, open rejections, budgets used. The lead
  updates it at every lifecycle change and re-reads it whenever its own context has been
  compacted or it is unsure what is in flight.
- `runlog/stage<N>.md` is the stage's record: dispatch time, each work item with owner and
  timestamps, each verdict with its revision, each rejection and what it caught, the gate
  table at acceptance, and the stage's wall time.
- Verdicts are saved by the verifier under `reviews/stage<N>/`, screenshots under
  `reviews/stage<N>/shots/`, outside the stage folders.

## 10. Final report

When the run ends (all stages accepted, or a blocker), the lead posts one message to the
room: stages accepted with their revisions, gates per stage, rejections and what they
caught, open risks, blockers with evidence.
