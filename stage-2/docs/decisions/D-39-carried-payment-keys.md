# D-39 carried stage-1 tests: payment key set

**Question.** Stage-1 acceptance tests assert the exact key set of a payment object
(`PAYMENT_KEYS`). Stage 2 adds a field.

**What the specification says.** Stage 2: "Payments created without an authorisation carry
`authorization_id: null`" (R2-CAP.6), and capture returns a payment "in exactly the shape
`POST /payments` returns".

**Choice.** `stage-2/acceptance/stage1/conftest.py` adds `authorization_id` to `PAYMENT_KEYS`.
Every carried test that compares key sets (payments, request pay, feed items, settlement members)
now expects 13 keys; values of the stage-1 fields are unchanged. Stage-1 row R-8.5 is marked
"changed by R2-CAP.4/6" in the stage 2 ledger.
