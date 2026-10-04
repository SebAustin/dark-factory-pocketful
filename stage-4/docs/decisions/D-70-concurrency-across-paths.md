# D-70 concurrency across paths

**Question.** Concurrent single corrections and batches. (open point 9)

**What the specification says.** "Concurrent corrections sharing any expected payment revision cannot both succeed."

**Choice.** All writes serialise on the single state lock; expected_revision is checked against the payment's latest revision inside the same lock hold that appends. Therefore among any concurrent single corrections and batches that name the same (payment, expected revision), exactly one can succeed; the others get 409 stale_revision (a batch fails as a whole, D-66 step 1). A batch commits all revisions and balance moves in one hold: readers see all or none.

**Effect on acceptance tests.** 20-way mixed race and an all-or-none reader under load.
