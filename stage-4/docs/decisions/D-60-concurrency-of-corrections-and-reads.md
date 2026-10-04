# D-60 concurrency of corrections and reads

**Question.** Concurrent corrections, payments and statement reads.

**What the specification says.** "Concurrent corrections using the same expected revision cannot both succeed." "Existing snapshots remain unchanged during concurrent payments or corrections." Stage 2: same results as some serial order.

**Choice.** All writes and reads run under the single state lock (stage 1/2 design), so they serialise; for N concurrent corrections with the same expected_revision and distinct keys exactly one gets 201 and the rest 409 stale_revision; a statement read sees either all or none of a concurrent write; snapshots are immune by D-50.

**Effect on acceptance tests.** Tests run 20 concurrent corrections and mixed write/read load with an invariant-checking reader.
