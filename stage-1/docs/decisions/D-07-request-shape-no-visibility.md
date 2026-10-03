# D-07 request shape no visibility

**Question.** May a request object carry a visibility field? Is `visibility` in POST /requests or /splits validated?

**What the specification says.** "A request carries no visibility of its own". Request field list has no visibility.

**Choice.** Request objects have no `visibility` key. `visibility` sent to /requests or /splits is an unknown field and ignored (not validated).

**Effect on acceptance tests.** Tests assert the request key set exactly as listed in §8.

**Constraining text.** §4 visibility paragraph; §3.4 unknown fields ignored.
