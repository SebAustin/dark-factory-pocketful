# D-18 seeded total after an import

**Question.** §1 says balances sum to the total seeded by the last `POST /_test/reset`. What is that total after `POST /_test/import`?

**What the specification says.** Import "atomically replaces the service's state" and is replacement, not merge; reset clears all state including imported state.

**Choice.** The service stores no separate "seeded total". The reference after an import is the balance sum of the imported state (equal to the source's total, since export is a snapshot of a state that already satisfied the invariant). Import never recomputes, regenerates or adjusts a balance. Import does not validate that the sum equals anything; it validates each balance (integer, 0 to 2^53) only.

**Effect on acceptance tests.** Tests that check the sum after an import compare it with the sum at export time.

**Constraining text.** §1 invariant 1; §10 "Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance."
