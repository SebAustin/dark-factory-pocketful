# D-08 third party on request

**Question.** A user who is neither requester nor payer calls pay/decline/cancel: 403 or 404?

**What the specification says.** Pay table: "The caller is not the request's payer → 403". §5: 404 also covers "not visible to this caller".

**Choice.** Builder returns 403 `forbidden` (literal endpoint table). 

**Effect on acceptance tests.** Tests assert 403 for the other party (requester paying, payer cancelling) and accept 403 or 404 for a third party.

**Constraining text.** §8 pay/decline/cancel tables; §5 404 row.
