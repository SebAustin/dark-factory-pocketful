# D-21 accept negotiation

**Question.** When does a shared route (/requests, /authorizations) return HTML?

**What the specification says.** "Return the UI for `Accept: text/html`; API requests without that header receive JSON."

**Choice.** HTML iff the Accept header lists the media type `text/html` (any position, q > 0), e.g. browser `text/html,application/xhtml+xml,*/*;q=0.8`. `*/*`, `application/json`, a missing header → JSON. Only GET is negotiated; POST /requests stays JSON. An HTML GET needs no bearer token (the page handles sign-in); a JSON GET without a token is 401. Responses add `Vary: Accept`.

**Effect on acceptance tests.** Tests: Accept text/html → content-type text/html; none, */*, application/json → JSON (401 without token).
