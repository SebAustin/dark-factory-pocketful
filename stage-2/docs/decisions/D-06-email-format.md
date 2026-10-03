# D-06 email format

**Question.** What is "of the form local@domain"? Are emails case-sensitive?

**What the specification says.** Only the shape is stated.

**Choice.** Valid iff exactly one `@`, non-empty local part, non-empty domain, no whitespace. Email uniqueness and login compare case-insensitively; the email is stored as given. Order: 422 (password/email/display_name) → 409 `email_taken` → 409 `handle_taken`.

**Effect on acceptance tests.** Tests use clearly invalid emails ("ada", "@x.com", "ada@", "") and do not probe case.

**Constraining text.** §6 signup table.
