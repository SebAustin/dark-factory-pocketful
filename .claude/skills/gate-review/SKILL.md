---
name: gate-review
description: Independent verification and two-axis review of a handed-off revision, ending in VERDICT ACCEPT or REJECT. Use when a seat receives an item review packet or a stage gate packet.
---

# Gate review

Adapted from Matt Pocock's `code-review` skill (MIT) and the agency's solution-verifier.
Skeptical and evidence based: everything you claim, you ran.

## 1. Pin the revision in your own worktree

The working tree is shared with seats still editing, so never judge it in place:

```sh
git worktree add --detach "$SCRATCH/review-<revision>" <revision>
cd "$SCRATCH/review-<revision>"
```

`$SCRATCH` is any folder outside the repository. Remove the worktree when the verdict is
sent (`git worktree remove --force <path>`). Record `git log --oneline <base>..<revision>`.

## 2. Item review (every work item): quick

1. Run the packet's DONE WHEN commands yourself; a mismatch with the reported output is a
   finding by itself.
2. Run the tests for the item's requirement ids against the artifact started from your
   worktree, on your own port range (PROTOCOL section 7).
3. Review the item's diff on both axes (section 4).
4. For a user facing item, run the screen check from section 3 on its screens now; screen
   defects are cheapest to fix before the stage gate.

## 3. Stage gate (once per stage): complete

Run every gate of PROTOCOL section 4 on the one revision:

- Build the artifact from scratch (no cache) and start it exactly as its run instructions
  say; wait for its health signal.
- Run this stage's acceptance suite and every earlier suite carried into this folder.
- Run each checker the task supplies, exactly as the task specifies, **in the background**:
  `nohup <command> > "$SCRATCH/checker-<revision>.log" 2>&1 &` then poll the log until it
  ends. A tool time limit is not a failure. Copy its final lines into the verdict.
- Stress the invariants: fire simultaneous and repeated writes at the same resources, read
  the state back, check each invariant the ledger lists, and repeat several times; a race
  passes once and fails on the third run.
- Confirm history only grew: `git merge-base --is-ancestor <last accepted> <revision>`.
- For user facing work: open each screen in a real browser at the required viewports, walk
  every listed state with realistic extreme data (longest text, largest number, empty
  lists), save screenshots, note console errors. Then **look at every screenshot** and judge
  it: wrapped or truncated values, overflow, overlap, unreadable contrast, controls off
  screen. A screenshot that was taken but not judged is not evidence; a visible defect in
  one is a blocking finding.

## 4. Two axes, reported separately

**Standards**: names that say what they hold, small functions, one place per invariant,
explicit error handling, no dead code or debug output, no secrets, no duplicated logic.
Label judgement calls as such.

**Spec**: for each requirement in scope: implemented, partial, missing or wrong, with its
quote. List behaviour no requirement asked for. Look specifically for code that recognises
a particular test input (fixed identifiers, magic values, special cased data); that is a
blocking finding.

Report the axes under separate headings so a clean one never hides a failing one.

## 5. Verdict

Use the format of PROTOCOL section 5. ACCEPT requires every applicable check green on this
revision. Each REJECT finding carries the requirement id, the specification quote, observed
versus expected, and a reproducing command. Save the verdict under `reviews/stage<N>/`,
commit it as yourself, and send it to the owner and to the lead.
