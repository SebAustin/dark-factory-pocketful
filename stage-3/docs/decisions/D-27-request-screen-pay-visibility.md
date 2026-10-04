# D-27 request screen pay visibility

**Question.** What visibility does the pay button on /requests use?

**What the specification says.** Not specified; pay body visibility optional, default public.

**Choice.** The button sends `{}` (default public) unless the screen offers an explicit privacy choice. Retries of the same click reuse the same key and body.

**Effect on acceptance tests.** Not asserted beyond 'payment created'.
