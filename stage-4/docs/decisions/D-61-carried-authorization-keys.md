# D-61 carried stage-2 tests: authorization key set

**Question.** Three carried stage-2 tests assert the exact authorization key set (D-32):
`test_R2_AUTH_3_AUTH_1_authorize_201_shape`, `test_R2_CAP_14_remaining_amount_everywhere`,
`test_R2_LIST_6_list_shape`.

**What the specification says.** Stage 3: "Authorizations expose `closed_at` (null while open; event
time when closed)" (R3-HH.9).

**Choice.** `stage-3/acceptance/stage2/s2lib.py` adds `closed_at` to `AUTH_KEYS`; nothing else in the
carried stage-2 suite changes. Stage-2 row R2-AUTH.3 is marked "changed by R3-HH.9" in the stage 3
ledger (Part B).
