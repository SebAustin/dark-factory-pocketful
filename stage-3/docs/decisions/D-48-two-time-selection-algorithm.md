# D-48 two time selection algorithm

**Question.** The exact computation behind as_of / known_at / statements.

**What the specification says.** KN section: select latest revision recorded at or before known_at, then apply by effective times; as_of inclusive; statement half-open.

**Choice.** For a user u and (T, K):
1. For each payment p with u as sender or receiver: S(p) = the revision with the largest recorded_at ≤ K; if none, skip p.
2. Signed amount a(p) = −S.amount if u sent p, +S.amount if u received p.
3. Balance(u, T, K) = opening(u) + Σ a(p) over p with S.effective_at ≤ T.
4. Statement [from, to) under K: entries = p with from ≤ S.effective_at < to, ordered by (S.effective_at, payment id code-point); opening_balance = opening(u) + Σ a(p) with S.effective_at < from; closing_balance = opening(u) + Σ a(p) with S.effective_at < to; balance_after(i) = opening_balance + Σ deltas of entries 0..i. Zero-amount S still produces an entry (delta 0). Each payment contributes at most one entry.
All comparisons per D-42. Current balance = Balance(u, +∞, N) and must equal the stored wallet balance.

**Effect on acceptance tests.** The property tests implement exactly this as the reference model.
