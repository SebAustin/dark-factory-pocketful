# D-42 instant parsing and comparison

**Question.** Which strings are valid instants in queries (as_of, known_at, from, to), bodies (effective_at) and fixtures (created_at, expires_at), and how are they compared? (open question 1)

**What the specification says.** "an RFC 3339 instant with an offset. Anything else — a naive local time, a bare date, an empty value — is 422".

**Choice.** Valid: `YYYY-MM-DD` `T|t` `HH:MM:SS` optional `.` + 1..9 digits, then `Z|z` or `±HH:MM` (offset hours 00–23, minutes 00–59); calendar-valid date and time; second 00–59 (a leap second `60` is 422). Everything else is 422 validation_failed: naive times, bare dates, empty, epoch numbers, a space instead of `T`, more than 9 fractional digits, `+24:00`.
Form-encoding artefact: in a query string an unencoded `+` decodes to a space; a value whose only defect is a single space immediately before a trailing `HH:MM` offset is read as `+HH:MM` (no other leniency).
Comparison: every instant is converted to an exact integer count of nanoseconds since the epoch (UTC); all comparisons (inclusive as_of, half-open windows, known_at selection, effective_at ≤ now, seeded created_at ≤ reset instant) use that integer. Offsets never matter: `13:20:00+02:00` ≡ `11:20:00Z`.
Repeated query parameter: the last occurrence wins (stage 1 parsing).

**Effect on acceptance tests.** Tests send the same instant in several offsets and fractional forms and expect identical results; invalid list in R3-ME.2.
