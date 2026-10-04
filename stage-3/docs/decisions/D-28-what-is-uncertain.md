# D-28 what is uncertain

**Question.** Which outcomes are 'lost responses' (pay-uncertain) vs refusals (pay-error)?

**What the specification says.** "If a payment response is lost, including after POST /payments commits, show pay-uncertain … Unknown outcomes are not confirmed rejections."

**Choice.** Uncertain: network error, connection reset/abort, timeout, any 5xx, an unparseable or non-JSON response. Refusal: any 4xx with the error envelope (shown in pay-error, which also refreshes balance/feed). The same split applies to request/split/authorize/capture forms (their own error element; pay-uncertain is only required for pay).

**Effect on acceptance tests.** Tests abort after the server commits and before; both must show pay-uncertain.
