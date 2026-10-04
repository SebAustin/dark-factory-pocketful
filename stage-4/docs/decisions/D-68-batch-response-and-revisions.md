# D-68 batch response and revisions

**Question.** Batch response shape and the new revisions.

**What the specification says.** "Return 201 with correction_batch_id, recorded_at and revisions in input order. All new revisions share recorded_at ... each revision also exposes correction_batch_id."

**Choice.** 201 {correction_batch_id (opaque, ≤ 64 chars), recorded_at (one D-41 tick, rendered µs +00:00), revisions: [revision objects in input order]}. Each revision object = the stage-3 revision shape + correction_batch_id: {payment_id, revision (= previous + 1), amount, effective_at (verbatim as supplied), recorded_at (= the batch's), reason, correction_batch_id}. Replay → 200 with the stored body even after newer revisions. Original payment/settlement receipts and their replays never change.

**Effect on acceptance tests.** Exact key sets asserted.
