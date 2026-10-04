# D-35 authorizations list shape

**Question.** Response envelope of GET /authorizations.

**What the specification says.** 'behave exactly as on GET /requests'.

**Choice.** `{"authorizations": [authorization...], "has_more": bool}`.

**Effect on acceptance tests.** Tests assert this shape.
