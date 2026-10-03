# D-12 import validation

**Question.** What is an "invalid state" on import?

**What the specification says.** Opaque format; must reject with 422 and leave destination unchanged.

**Choice.** Import validates the entire object (track == "pocketful", format_version == 1 as an integer, state an object passing the same structural checks as the store) before swapping. Body that is not a JSON object → 400 malformed_request.

**Effect on acceptance tests.** Tests send missing state, wrong track, version 2, state {} and state "x"; accept 422 for these; destination must be unchanged.

**Constraining text.** §10.
