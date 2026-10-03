---
name: spec-ledger
description: Turn a specification into a numbered requirements ledger with verbatim quotes, a coverage table and a domain glossary. Use when a seat receives a specification, critiques a plan against one, or asks "what does the spec require that no check asks about?".
---

# Spec ledger

The ledger is the factory's single source of truth for *what must be true*. Tests, plans,
reviews and verdicts all cite its ids. A requirement that is not in the ledger will not be
built, tested or checked, so the ledger's completeness is the stage's ceiling.

## Steps

1. **Read the whole specification once, slowly, end to end.** No skimming of sections
   that look familiar from an earlier stage: later stages change earlier behaviour.
2. **Extract.** Walk the text sentence by sentence. Every sentence that constrains
   behaviour becomes one row. Constraint signals: must, must not, never, always, only, at
   most, at least, exactly, unless, otherwise, if, when, before, after, every, each, all,
   none; numbers, units, limits and ranges; tables; status and error codes; field lists;
   examples (each example is a requirement: the system must produce exactly that output).
3. **Hunt the hidden rows.** For each section, ask the questions a quick reading skips and
   add a row for each answer the text gives:
   - Boundaries: the smallest, largest, zero, empty, one past each limit, wrong type,
     missing field, extra field, duplicate value, unknown reference.
   - Precedence: when two errors apply at once, which one wins?
   - Retries: the same request sent twice, with the same and with a different body.
   - Concurrency: two writers racing for the same thing; what invariant must survive?
   - Time: ordering, time stamps, as of queries, what "now" means.
   - State: what a reset, an import or an upgrade does to existing records.
   - Visibility and permission: who may see or change what; what others must not see.
   - Every invariant stated once in a scope section applies to *every* operation.
4. **Write the ledger** to the stage folder at `docs/ledger.md`:

   ```
   | id | section | requirement (verbatim quote) | kind | proof |
   ```
   - id: `R<stage>.<n>`, stable once published; never renumber.
   - kind: behaviour, error, invariant, limit, format, screen, operational.
   - proof: the acceptance test name, or `untestable: <reason>`.
5. **Glossary.** Write `docs/glossary.md`: each domain term, one line of meaning, and the
   terms it must not be confused with. No implementation detail.
6. **Risk list.** At the end of the ledger, list the requirements most likely to be built
   wrong and why.

## Completion criterion

Every constraining sentence of the specification maps to at least one row, and every row
has a proof that is a test name or a stated reason. Count the rows per section and
compare against the section's length; a long section with few rows is not done.

## Critiquing a plan against the ledger

Return PASS or REVISE. REVISE lists numbered defects, each with a requirement id:
missing requirement, invariant enforced in more than one place (or nowhere), check then
write races, behaviour invented with no requirement behind it, error precedence unclear.
