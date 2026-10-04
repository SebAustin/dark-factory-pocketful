# D-55 testing invariants in every view

**Question.** How the suite proves 'sum of balances equals the seeded total in every historical view' and nonnegativity. (open question 10)

**What the specification says.** "The sum of balances must equal the seeded total in every historical view."

**Choice.** Property tests build a history (seeded dated payments, API payments, request pays, settlements, captures, voids, expiries, and accepted corrections incl. backdated, zero and same-amount ones), collect every boundary instant B (all effective_at, recorded_at, created_at, hold event times), and evaluate GET /me for EVERY user at T ∈ {−∞-ish, each b−1µs, b, b+1µs, far future} × K ∈ {each recorded_at −1µs/=, N}. Assert Σ total = seeded total, every total ≥ 0, available = total − held ≥ 0, and each value equals the D-48/D-51 reference model. Statements for every user over windows between consecutive boundaries must satisfy opening + Σ delta = closing and match the model.

**Effect on acceptance tests.** Implemented in stage-3/acceptance/stage3/test_prop_*.py.
