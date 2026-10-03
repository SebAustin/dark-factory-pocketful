# D-25 amount formatting

**Question.** Grouping separators and sign in formatted amounts.

**What the specification says.** "the decimal with exactly `minor_units` decimal places, a single space, then the currency code"; "no sign".

**Choice.** No thousands grouping, ASCII digits, `.` decimal point, regular space U+0020. Applies to every testid that says 'exactly the formatted amount' (wallet, feed, request, split share, authorization amount/captured). Direction (sent/received) is shown by a separate element, never by a sign in the amount text.

**Effect on acceptance tests.** Tests compare text exactly, e.g. `1234567.89 EUR`.
