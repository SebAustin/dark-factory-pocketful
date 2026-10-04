# D-40 carried stage-1 tests: GET /me shape

**Question.** `test_R8_1_R4_7_me_shape_seeded` compares `GET /me` to an exact object.

**What the specification says.** Stage 2 `GET /me` keeps `balance` and adds `total`
(= `balance`), `available` and `held`; "With no open holds, `balance`, `total` and `available`
agree and `held` is zero" (R2-ME.1, R2-HOLD.11).

**Choice.** The carried test expects the stage-2 object with `total = available = balance` and
`held = 0` for a fixture without authorizations. No other carried test changes for `/me` (they
read `balance` only). Stage-1 row R-8.1 is marked "changed by R2-ME.1".
