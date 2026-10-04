# D-09 split caller omitted

**Question.** If the caller is not in participant_handles, is the caller added to the split?

**What the specification says.** "The caller may be included in participant_handles or omitted." Shares cover "every participant" in the order given.

**Choice.** n = len(participant_handles). An omitted caller gets no share; every listed handle gets a share and a request. `shares` lists exactly the given handles.

**Effect on acceptance tests.** Tests: [bob, cy] by ada for 3000 → shares 1500/1500, two requests.

**Constraining text.** §8 splits.
