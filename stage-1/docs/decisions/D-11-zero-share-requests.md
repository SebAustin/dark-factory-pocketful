# D-11 zero share requests

**Question.** A 0 share creates a request of amount 0; how does it behave?

**What the specification says.** "A share of 0 is legal and still produces a request for that participant."

**Choice.** The request is `pending` with amount 0; paying it creates a payment of amount 0 (201) and marks it paid; decline/cancel work normally. POST /requests still rejects amount 0.

**Effect on acceptance tests.** Tests assert the request exists with amount 0 and pending; paying it is asserted 201.

**Constraining text.** §9.
