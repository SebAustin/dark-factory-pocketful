# D-05 character counting

**Question.** How are "characters" counted for note (200), password (8), key (255), handle truncation (20)?

**What the specification says.** Not stated.

**Choice.** Unicode code points (not bytes, not UTF-16 units, not grapheme clusters).

**Effect on acceptance tests.** Tests use ASCII at the boundaries (200/201, 7/8, 255/256) and emoji only in round-trip tests below the limit.

**Constraining text.** §8 "`note` longer than 200 characters".
