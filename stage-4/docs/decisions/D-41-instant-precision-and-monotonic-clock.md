# D-41 instant precision and monotonic clock

**Question.** Which precision do server-assigned instants have, and how do recorded times for one payment strictly increase when two corrections land in the same second? (open question 1)

**What the specification says.** "Recorded times for one payment strictly increase." Stage 1 only requires RFC 3339 with an explicit offset; stage 1/2 builds emit whole seconds.

**Choice.** Every server-assigned instant (payment created_at, settlement committed_at, correction recorded_at, authorization created_at / capture / void / closed_at, the read instant) comes from ONE service-wide monotonic clock with microsecond resolution: `t = max(wall_clock_µs, last_assigned + 1 µs)`, taken while the state lock is held. Consequences: all server-assigned instants are unique and strictly increasing in commit order; recorded_at of successive revisions of one payment strictly increase even within one second; an API payment can never tie with an earlier one.
Rendering: `YYYY-MM-DDTHH:MM:SS.ffffff+00:00` (always 6 fractional digits, numeric offset) for server-assigned instants. Seeded, imported and client-supplied instants are stored at their full precision and rendered exactly as received (see D-42/D-47). Expiry `expires_at = created_at + ttl` keeps the microseconds of created_at.
Rejected alternative: whole seconds plus a +1 µs bump only on collision — a payment made at 12:00:00.7 would render 12:00:00 and then be wrongly visible to `known_at=12:00:00.5`.

**Effect on acceptance tests.** Tests compare instants by value, never by string; R3-REV.8 makes three corrections within one second; R3-TS.10 checks strictly increasing created_at over rapid payments.
