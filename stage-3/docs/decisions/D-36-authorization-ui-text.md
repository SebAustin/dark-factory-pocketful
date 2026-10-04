# D-36 authorization ui text

**Question.** Text of authorization-expires and the capture prefill.

**What the specification says.** 'Text is the RFC 3339 expires_at'; 'pre-filled with the remaining amount' (decimal input).

**Choice.** authorization-expires-{id} text is exactly the API's `expires_at` string. The capture input value is the remaining amount as a decimal with exactly minor_units places and no currency code (`15.00`; JPY `1200`).

**Effect on acceptance tests.** Tests compare exactly.
