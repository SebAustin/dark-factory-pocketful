---
name: slice-tdd
description: Test-first vertical slices for building or testing a service from a requirements ledger. Use when implementing a work item, writing acceptance tests, or fixing a rejected item.
---

# Slice TDD

Adapted from Matt Pocock's `tdd` skill (MIT). Red, then green, one vertical slice at a time.

## What a good test is

A test verifies behaviour through a public interface, never internals. It reads like the
requirement it proves and survives any refactor that keeps behaviour. Its expected values
come from an independent source of truth: the specification's text, its worked examples,
or a value computed by hand from the rule. A test that recomputes the expected value the
way the code does is tautological and proves nothing.

## Seams

A **seam** is the boundary you test at. For a network service the primary seam is the
public interface of the running artifact: acceptance tests drive it exactly as a
client would, at the address in the `TARGET_URL` environment variable (PROTOCOL section 7). Inner seams (a pure function holding a calculation or a state transition)
are allowed for logic with many cases, such as arithmetic and rule tables.

## The loop

1. Pick the next requirement id in the work item.
2. Write one test for it at the agreed seam. Run it. Watch it fail for the right reason.
3. Write the least code that makes it pass. Run the whole suite.
4. Commit your own paths when a requirement turns green (PROTOCOL section 6).
5. Repeat until every requirement in the item is green, then run DONE WHEN.

Each test is a **tracer bullet**: write it in response to what the last slice taught you.
Writing every test first and every line of code after is horizontal slicing; avoid it.

## Rules

- Name each test after its requirement id and the behaviour: `R1.14 rejects a reused
  idempotency key with a different body`.
- Cover the error paths and boundaries the ledger lists, not only the happy path.
- Concurrency requirements get a real concurrent test: many simultaneous requests, then an
  assertion on the invariant, repeated enough times to be meaningful.
- When an existing check fails, locate the requirement it exercises and fix the rule for
  all inputs. Code that branches on a particular test's data is a defect.
- Refactoring is a separate step after green, never mixed into a red to green cycle.
