# D-30 seeded authorization validation

**Question.** Which seeded authorization defects make reset fail?

**What the specification says.** Only 'holds over balance → 422' is stated.

**Choice.** Reset 422 changing nothing for: unknown from/to user, from == to, amount not an integer 1..1e9, visibility not public/private, status not one of four, missing or non-RFC 3339 `expires_at`, duplicate ids, `captured_amount` (optional, default 0) outside 0..amount. Optional `note` default "", `visibility` default public, `created_at` default reset time. Only `open` holds with expires_at > now count toward the over-balance check.

**Effect on acceptance tests.** Tests assert unknown user and holds-over-balance; others accept 422.
