# D-51 historical holds

**Question.** How held/available are computed at (T, K); seeded holds; closed_at. (open question 8)

**What the specification says.** Historical holds section.

**Choice.** Hold amount of authorization a at instant t (known at K): 0 if a's creation time c > K or t < c. Otherwise start with a.amount at c; for each capture event at time e with e ≤ K and e ≤ t: subtract its captured amount (a non-final capture reduces; a final capture also releases the remainder, setting the hold to 0); a void at v ≤ K and v ≤ t sets it to 0; expiry: if still open at t ≥ expires_at → 0 (expiry is known as soon as creation is known, also for future T). held(u,T,K) = Σ over a with from = u. total(u,T,K) per D-48 (captures are payments whose revision 1 is at the capture instant); available = total − held.
Event times: creation = created_at; capture = the capture payment's created_at; void = void instant; expiry = expires_at. closed_at: null while open; captured → instant of the closing capture; voided → void instant; expired → expires_at.
Seeded authorizations: open → created at supplied created_at, else reset instant R; must not be in the future (> R → 422). Seeded closed (captured/voided/expired) hold nothing at any instant (no reconstructed lifecycle); closed_at = supplied closed_at if given, else expires_at for expired, else supplied created_at, else R. Seeded captured amounts are not payments unless their payments are seeded.
Without as_of: T = N. Current (no params) equals stage-2 held.

**Effect on acceptance tests.** Property tests use this model; edge tests at exactly c, e, v and expires_at (±1 µs).
