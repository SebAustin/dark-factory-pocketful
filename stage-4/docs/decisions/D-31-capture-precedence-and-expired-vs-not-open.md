# D-31 capture precedence and expired vs not open

**Question.** Which error wins on capture, and expired vs not_open?

**What the specification says.** Capture table lists not_open, expired, exceeds, validation, forbidden, not_found; void says expired → not_open.

**Choice.** Capture: 401 → 400 malformed body → 400 missing key → 422 key length → replay/409 reuse → body fields (400 `final` wrong type, 422 `amount` rules) → 404 → 403 → 409 `authorization_expired` when the stored status is open (or expired) and expires_at ≤ now → 409 `authorization_not_open` when captured/voided → 422 `capture_exceeds_authorization`. Void: 404 → 403 → voided → 200; captured or expired (stored or by clock) → 409 not_open.

**Effect on acceptance tests.** Tests assert expired on a clock-expired open authorization; accept expired or not_open on a seeded `expired`.
