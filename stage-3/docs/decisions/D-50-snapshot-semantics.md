# D-50 snapshot semantics

**Question.** What a snapshot freezes, validation with a snapshot, token lifetime incl. export/import. (open question 7)

**What the specification says.** "It freezes the caller's selected revisions, window, balances, entries and default to at that read. ... Only limit and offset may accompany a snapshot; supplying from, to or known_at with it gives 422 ... Unknown token, another user's token, or a token from before reset gives 404 ... Tokens last until reset."

**Choice.** Every GET /statement without `snapshot` mints a fresh opaque token bound to (caller, from, resolved to, resolved K, read instant N) and to the full computed result (entries with balances, opening, closing). Paging with the token returns slices of exactly that result; has_more is computed on it. Implementation may store the materialised result or the parameters with K clamped to min(K, N) — the two are observably identical because every later revision has recorded_at > N and effective_at ≤ recorded_at (D-41/D-46), and statements contain no hold events.
With `snapshot`: any presence of from, to or known_at (even empty) → 422; limit/offset validated as usual (422); unknown parameters ignored. Token not found, minted by another user, or minted before the last reset → 404 not_found (no distinction).
Lifetime: until the next reset — and only reset ends it ("Tokens last until reset"). Snapshots live in the process (not in the exported state); an import does NOT invalidate them: a token minted before an import still pages its frozen result afterwards (its result never depended on later state). A fresh container that imports an export has no tokens ("No storage survival across container restarts is required"). Revised at the stage 3 plan gate (was: tokens travel inside the export).

**Effect on acceptance tests.** Tests: frozen after payments, corrections (incl. backdated), captures, voids, expiries; 422 combos; 404 across users and after reset; paging/has_more.
