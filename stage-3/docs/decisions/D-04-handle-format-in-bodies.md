# D-04 handle format in bodies

**Question.** Is a correctly typed but format-invalid handle ("BOB", "", 21 chars) 404 or 422?

**What the specification says.** §5: invalid format → 422 unless an endpoint specifies otherwise; endpoints specify 404 for "No user has that handle".

**Choice.** Builder returns 422 `validation_failed` for handles not matching `^[a-z0-9_]{1,20}$` (explicit format rule); 404 for well-formed unknown handles.

**Effect on acceptance tests.** Acceptance tests accept 404 or 422 for format-invalid handles; assert 404 for well-formed unknown handles.

**Constraining text.** §5 "A field of the correct JSON type with an invalid format ... gives 422".
