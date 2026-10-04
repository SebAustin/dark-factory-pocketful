# D-34 replay body after new fields

**Question.** What does 'New fields do not change idempotency body equality' mean?

**What the specification says.** Ambiguous.

**Choice.** (a) Request bodies are still compared as JSON values, so adding `final` changes the body (`{}` ≠ `{"final":true}`); (b) a replay returns the originally stored response verbatim, even if later state (more captures, a stage-2 field like remaining_amount) changed, and even if the stored receipt predates stage 2 (an imported stage-1 receipt without `authorization_id`).

**Effect on acceptance tests.** Tests: replay of a capture after further captures returns the original body.
