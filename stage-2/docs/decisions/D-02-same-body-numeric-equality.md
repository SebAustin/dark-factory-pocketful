# D-02 same body numeric equality

**Question.** Is `{"amount":1000}` the same body as `{"amount":1e3}` / `1000.0` for replay?

**What the specification says.** "Same body" means the same JSON value after parsing. 1000, 1000.0 and 1e3 "all represent the same valid minor-unit amount".

**Choice.** Compare bodies as parsed JSON values with numbers compared by numeric value (1000 == 1000.0 == 1e3). Booleans are never equal to numbers (true ≠ 1).

**Effect on acceptance tests.** Tests: replay of 1000 with 1e3 must not be 409; the suite accepts 200 (asserts not 409 and no second debit).

**Constraining text.** §4 integral numeric value; §7 "same JSON value after parsing".
