# D-43 read instant defaults and echo

**Question.** How do omitted temporal parameters resolve, alone and combined, and what does the response echo? (open question 2)

**What the specification says.** "Omission means everything known when the read begins." "from defaults to the opening of the wallet and to to now." "Without as_of, use the instant the request began." "The response carries as_of back, exactly as given." "Echo supplied known_at exactly." "Without temporal query parameters the response retains the existing money fields".

**Choice.** Each read takes one read instant N from the monotonic clock (D-41) while the state is consistent; N is "now" and "the instant the request began" for every default in that read.
GET /me: T = as_of or N; K = known_at or N. Both omitted → exactly the stage-2 response (same keys, current corrected values). as_of only → K = N. known_at only → T = N. Future T and/or K allowed: a future K selects everything recorded so far (nothing is recorded in the future); a future T applies all selected revisions (effective_at ≤ now) and expires open holds at their deadlines (D-51).
GET /statement: from omitted → −∞ (before the wallet opened, so opening_balance = wallet opening balance); to omitted → N; K omitted → N.
Echo: `as_of` and `known_at` appear in the response only when supplied, as the exact strings received (after URL decoding; the D-42 space-for-plus repair is NOT applied to the echo). No `from`/`to` echo is required; a statement echoes `known_at` when supplied.

**Effect on acceptance tests.** Tests assert the stage-2 /me key set without params, echo verbatim with params, and that as_of-only / known_at-only equal the explicit N-based results.
