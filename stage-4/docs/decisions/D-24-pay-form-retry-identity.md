# D-24 pay form retry identity

**Question.** When does a pay submission reuse its Idempotency-Key?

**What the specification says.** "Submitting it again without changing a field must not send another payment … Changing a field makes the next submission a new payment request."

**Choice.** The form holds one pending key. It is minted on the first submission and kept until a field changes (any input/change event on any pay field, even if later reverted). Kept across success (resubmit → 200 replay), uncertain outcomes (retry → same key, byte-identical body) and refusals (a 4xx leaves the key reusable per §7, so reuse is harmless). The body is built from the same parsed values, so equal fields give the same JSON value. The same rule applies to the request, split and authorize forms.

**Effect on acceptance tests.** Tests observe the key and body on the wire.
