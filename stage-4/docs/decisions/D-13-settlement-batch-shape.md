# D-13 settlement batch shape

**Question.** Which settlement defects are "malformed batch shape" (422) versus wrong JSON type (400)?

**What the specification says.** "malformed batch shape is 422 validation_failed" (endpoint-specific, overrides §5's 400).

**Choice.** Every defect inside `transfers` — missing, not an array, 0 or >32 entries, an entry that is not an object, a missing/ill-typed handle — is 422 `validation_failed`. Within one entry the order is: shape/amount/note/visibility 422 → `self_payment` 422 → unknown handle 404. Entries are scanned in input order and the first erroneous entry decides; the funds check runs only when every entry is valid.

**Effect on acceptance tests.** Tests assert 422 for missing/not-array/empty/33/non-object; accept 400 or 422 for ill-typed handles inside an entry.

**Constraining text.** §11.
