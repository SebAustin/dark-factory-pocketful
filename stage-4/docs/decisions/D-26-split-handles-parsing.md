# D-26 split handles parsing

**Question.** How is `split-handles` parsed?

**What the specification says.** "handles separated by commas, in order".

**Choice.** Split on `,`, trim whitespace around each, keep order. Empty segments (`ada,,bob`, trailing comma) and duplicates are shown as `split-error` without posting; handles are not lowercased or otherwise changed (an invalid handle is sent and the server's 404/422 is shown). The caller may be listed or omitted (D-09).

**Effect on acceptance tests.** Tests type `ada, bob,cy` and expect three shares in that order.
