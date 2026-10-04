# D-75 carried suite changes stage4

**Question.** Which carried stage 1–3 tests change.

**What the specification says.** Stage 4 adds refund_of to payments, correction_batch_id to revisions, and (L10) exports snapshots.

**Choice.** Carried suites change only here, each citing this record: PAYMENT_KEYS (+refund_of) in the stage-1, stage-2 and stage-3 copies; REVISION_KEYS / ENTRY_KEYS (+correction_batch_id) in the stage-3 copy; stage-3 test_R3_UPG_5_stage3_round_trip: a token minted before export → reset → import of that export now pages (L10) instead of 404; test_R3_SNAP_5_SNAP_6 keeps its stage-3 expectations except where L10 differs. No other carried test changes.

**Effect on acceptance tests.** Applied in S4.A.
