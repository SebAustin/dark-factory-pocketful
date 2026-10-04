# D-69 correction batch id exposure

**Question.** Where correction_batch_id appears. (open point 7)

**What the specification says.** "each revision also exposes correction_batch_id."

**Choice.** Every revision object everywhere carries correction_batch_id: the batch's id for revisions created by a batch, null for revision 1 and single corrections. Surfaces: GET /payments/{id}/revisions items, the batch response, single-correction 201/replay bodies created in stage 4 (stored stage-3 replays stay verbatim, D-72), and statement entries (alongside revision, effective_at, recorded_at).

**Effect on acceptance tests.** Tests read it on /revisions and statements.
