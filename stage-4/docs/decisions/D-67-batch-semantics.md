# D-67 batch semantics

**Question.** How a batch applies.

**What the specification says.** Batch section.

**Choice.** Each item behaves like a single correction of that payment by an operator: difference = new − current amount moves between that payment's own two wallets (increase debits the original sender, decrease the original receiver). Combined effect: all differences applied together for the available and historical checks (net per wallet). Item fields: expected_revision, amount (0..1e9), effective_at (≤ now, RFC 3339), reason (1..200) — all required, same typing as D-46. Unknown fields ignored at both levels. The operator need not be a party. Members of one settlement must all be present with identical effective instants; non-members may have any effective times.

**Effect on acceptance tests.** Tests cover net affordability and per-wallet movement.
