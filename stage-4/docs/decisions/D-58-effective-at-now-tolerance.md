# D-58 effective at now tolerance

**Question.** Is a client-supplied effective_at slightly ahead of the server clock accepted?

**What the specification says.** "effective time is an RFC 3339 instant not later than now."

**Choice.** Strict: effective_at must be ≤ the correction's read instant N (server clock). No tolerance window. Clients wanting 'now' should send an instant at or before their own current time on the same host.

**Effect on acceptance tests.** Tests use instants at least 1 s in the past for accepted cases and ≥ 2 s in the future for rejections.
