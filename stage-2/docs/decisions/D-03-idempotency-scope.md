# D-03 idempotency scope

**Question.** Is the key scoped per user only, or per (user, method, path)?

**What the specification says.** "The same key with the same body on a different path is a different request, not a replay, and must succeed normally."

**Choice.** Store and look up keys by (user, method, full path incl. request id, key). Same key on a different path never interacts with the first use, whatever the body.

**Effect on acceptance tests.** Tests assert same key + same body on another path → 201. Same key + different body on another path is not asserted.

**Constraining text.** §7 replay definition.
