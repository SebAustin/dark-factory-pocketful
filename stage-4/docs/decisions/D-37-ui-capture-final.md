# D-37 ui capture final

**Question.** Must the UI support non-final capture?

**What the specification says.** Extended capture mode is defined for the API; UI lists only amount input and capture button.

**Choice.** The UI capture sends `{"amount": n}` (final by default). A non-final option is allowed but not required. Capturing less than the remaining amount from the UI therefore releases the rest.

**Effect on acceptance tests.** Tests capture partially from the UI and expect status captured and available restored.
