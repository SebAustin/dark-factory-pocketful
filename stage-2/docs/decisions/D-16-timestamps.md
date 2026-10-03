# D-16 timestamps

**Question.** Format of timestamps and of seeded records' created_at.

**What the specification says.** RFC 3339 with explicit offset.

**Choice.** Emit `YYYY-MM-DDTHH:MM:SS+00:00` (numeric offset, second precision allowed). Seeded payments/requests get created_at at reset time. Imported records keep their exported timestamps.

**Effect on acceptance tests.** Tests accept any RFC 3339 timestamp with an offset (`Z` or ±hh:mm).

**Constraining text.** §3.4.
