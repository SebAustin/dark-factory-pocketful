# D-23 decimal input grammar

**Question.** Exact grammar for amount inputs.

**What the specification says.** Examples only: `15.00`, `15`, `15.5` valid; `15.005` and nonnumeric rejected without a request.

**Choice.** After trimming surrounding whitespace, valid iff `^[0-9]+(\.[0-9]+)?$` with at most `minor_units` fractional digits (so with minor_units 0 no decimal point at all). Rejected client-side with the form's error element and no request: empty, sign (`+`/`-`), exponent, comma, grouping spaces, `.5`, `15.`, too many places. Conversion uses integer/string arithmetic, never floats. Values that parse but fail server rules (0, > 1e9) are sent and the server's 422 is shown in the same error element.

**Effect on acceptance tests.** Tests assert the spec's examples plus `abc`, empty, `1e3`, `15,00`, JPY `15.0`, BHD `1.0005`: error shown, zero POSTs.
