# D-14 empty body

**Question.** An empty request body on decline/cancel/pay?

**What the specification says.** Decline/cancel define no body; pay's body is optional fields only. Unparseable bodies are 400.

**Choice.** Decline and cancel ignore the body entirely. For pay, an empty body (zero bytes) is treated as `{}`; any non-empty unparseable body is 400.

**Effect on acceptance tests.** Tests send `{}` explicitly to pay and no body to decline/cancel.

**Constraining text.** §8.
