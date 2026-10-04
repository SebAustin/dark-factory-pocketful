# Stage 2 UI plan — Pocketful wallet screens

Packet S2.U. Author: Designer. Sources: `runlog/stage2-spec.md` (§ "Product and visual
direction", every `data-testid` table, "Competing clients and uncertain outcomes", "Existing
clients after an upgrade", "Authorizations and captures"), `runlog/stage1-spec.md` (§4, §5, §7, §9).
Owned paths: `stage-2/web/**`, this file, `stage-2/tools/ui_*.py` (browser checks). Nothing in `app/`.

## 0. Shape in one paragraph

One static shell, `web/app.html`, served for every UI route; plain ES modules, one stylesheet, no
build step, no network, no inline script or style (so any CSP works). `web/assets/js/app.js` reads
`location.pathname`, mounts the matching screen into `<main>`, and talks to the existing JSON API with
`fetch`. Navigation links are real `<a href>`; the router intercepts same-origin clicks with
`history.pushState` so in-memory state (idempotency keys, pending retries) survives navigation, and a
hard load of any URL works because the server returns the same shell. Rendering is plain DOM building
through a 40-line `h()` helper that sets text with `textContent` only (never `innerHTML`: notes are
verbatim user text).

## 1. Visual direction

**Direction: "paper ledger".** A calm, printed-statement feel: warm paper ground, deep ink text,
one deep teal that means "act / confirmed", and a small set of semantic tints for the money states.
Not a dashboard: no sidebar, no card grid. A single narrow reading column on mobile; on desktop a
two-column composition where the left column is the *money* (headline number, then the three action
forms) and the right column is the *record* (activity feed), separated by a hairline rule like a ledger
margin. The headline number is set in a serif at display size; everything else is quiet sans.

### 1.1 Type: deliberate system stacks, no font files

Two stacks, both on every device, both already inside the image (nothing to ship, nothing to fetch,
no licence question, no FOUT):

- Display and figures: `ui-serif, "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif`
  (old-style serif gives the balance a printed, trustworthy look).
- Text and controls: `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`.
- All amounts: `font-variant-numeric: tabular-nums lining-nums`. All amounts and ids that must not
  break: `white-space: nowrap`.

Scale (rem, 1rem = 16px): `--t-xs .75`, `--t-sm .875`, `--t-md 1`, `--t-lg 1.25`, `--t-xl 1.75`,
`--t-hero: clamp(1.75rem, 11cqw, 4rem)`. The hero number lives in a container with
`container-type: inline-size`, so its size follows the container width: the longest amount the spec
allows (2^53 minor units, `90071992547409.92 EUR`, 21 characters) still fits one line at 375 px.
Weights: 400 body, 600 labels and buttons, 700 only for the hero. Line height 1.45 text, 1.1 numbers.

### 1.2 Palette and contrast (measured, WCAG 2.x relative luminance)

| Token | Hex | Used for | Contrast |
|---|---|---|---|
| `--paper` | `#F5F2EB` | page ground | — |
| `--surface` | `#FFFFFF` | form panels, inputs | — |
| `--ink` | `#1D2B29` | body text | 13.14 on paper, 14.69 on surface |
| `--ink-2` | `#4B5B58` | secondary text, labels | 6.40 on paper, 7.15 on surface |
| `--ink-3` | `#5C6B68` | captions, timestamps | 5.00 on paper |
| `--accent` | `#0E5A53` | primary button fill, links, confirmed | white on accent 8.06; accent on paper 7.21 |
| `--rule` | `#D8D2C4` | hairlines (decorative only) | — |
| `--field` | `#6E7D78` | input and button borders | 3.86 on paper, 4.31 on surface (>= 3:1 UI rule) |
| `--focus` | `#1F5FBF` | 3 px focus ring + 2 px offset | 6.09 on white, 5.45 on paper |
| `--ok` / `--ok-bg` | `#1B6636` / `#E3F1E6` | confirmed, received | 6.00 |
| `--held` / `--held-bg` | `#7A4E00` / `#F8EACB` | held funds, open authorisation, pending | 6.04 |
| `--pending` / `--pending-bg` | `#2F538C` / `#E2E9F5` | pending request, loading | 6.29 |
| `--refused` / `--refused-bg` | `#9C2226` / `#FBE3E1` | refused, declined, errors | 6.43 |
| `--unsure` / `--unsure-bg` | `#5E3592` / `#EDE5F7` | uncertain outcome | 7.15 |
| header ground | `--ink` | top bar | white on ink 14.69; inactive link `#C9D3CF` 9.58 |

Every text pair is >= 5:1 (AA needs 4.5:1; large text 3:1). Colour is never the only signal: each
state also has an icon glyph (inline SVG, `aria-hidden`) **and a word**.

### 1.3 Spacing, radius, elevation

Spacing is deliberately uneven (a 4-based scale with larger jumps between groups):
`--s1 4px`, `--s2 8px`, `--s3 12px`, `--s4 20px`, `--s5 32px`, `--s6 56px`. Inside a group use s2/s3,
between groups s5, around the hero s6. Radii: `--r-sm 6px` (inputs, badges), `--r-lg 14px`
(panels). One elevation: panels sit flat on the paper with a 1px `--rule` border; only the
sticky mobile tab bar and the toast-like status line carry a soft shadow
(`0 -1px 0 var(--rule), 0 -8px 24px rgb(29 43 41 / .08)`). Touch targets >= 44 x 44 px.

### 1.4 State vocabulary (visual + behavioural)

| State | Look | Words | Where |
|---|---|---|---|
| available | hero serif number, `--ink`, largest thing on screen; caption "Available to spend" | — | `wallet-available` |
| total | `--ink-2`, `--t-lg`, label "Total balance" | — | `wallet-balance` |
| held | amber pill with lock glyph, label "On hold" | "On hold 20.00 EUR" | `wallet-held`, absent when 0 |
| pending | blue-grey pill, clock glyph | "Pending" | requests |
| open authorisation | amber pill | "Open" | authorisations |
| loading | skeleton bars (no `0.00` placeholder, no `wallet-*` test ids until data exists), `aria-busy="true"`, buttons disabled with inline spinner | "Loading…" / "Sending…" | everywhere |
| success | green tint line with check glyph, only after the server answered 2xx **and** the refresh finished | "Sent 15.00 EUR to bob" | next to the form's submit |
| refused | red tint box, cross glyph, `role="alert"`, server message verbatim after a friendly lead | "Not enough available funds" | `*-error` |
| uncertain | violet tint box, dashed border, question glyph, `role="status"` | "We didn't get an answer. Your payment may or may not have gone through. Retrying is safe: it can't pay twice." | `pay-uncertain` |
| received / sent | feed chip with arrow glyph and word "Received" / "Sent" | — | feed |
| private | lock glyph + "Private" chip | — | feed, authorisations |
| declined / cancelled / voided / expired | grey-red neutral badge with strike glyph | the word | lists |
| paid / captured | green badge with check | the word | lists |
| stale (cancelled elsewhere) | row refreshes, buttons disappear, refused box above the list | "That request was cancelled, so it can't be paid." | `request-error` |

Motion: 150 ms opacity/transform only; `prefers-reduced-motion: reduce` removes it. No parallax, no gradients.

## 2. Screen map

Common shell (all routes): header with wordmark "Pocketful" (links to `/`), primary nav
`Wallet /`, `Requests /requests`, `Split /split`, `Authorizations /authorizations`; signed-in
right side: `current-user` (display name, visible on every screen), `current-handle` (text **exactly**
the handle; the "@" is drawn by CSS `::before`, so `textContent` has none), `logout-button`.
Signed-out right side: "Log in" `/login`, "Sign up" `/signup` (nav items hidden). On <= 640 px the four
nav items become a fixed bottom tab bar (icon + label, 56 px high) and the header keeps wordmark +
user chip; on wider screens the nav sits in the header. `aria-current="page"` marks the active link.
Signed-out visit to `/`, `/requests`, `/split`, `/authorizations` replaces history with `/login`.
Signed-in visit to `/login` or `/signup` replaces with `/`.

A polite live region `#status` (`role="status"`) announces success lines and refresh failures.

### 2.1 `/signup` and `/login`

| testid | Present |
|---|---|
| `signup-email`, `signup-password`, `signup-display-name`, `signup-submit` | always on `/signup` |
| `login-email`, `login-password`, `login-submit` | always on `/login` |
| `auth-error` | only while an error exists (removed on the next submit and on input) |

Each input has a visible label above it (`<label for>`), `autocomplete` hints, password
`type=password` with a "Show" toggle (not a testid). Submit disabled + spinner while in flight. Errors:
409 `email_taken`/`handle_taken` -> "That email/handle is already registered"; 422 -> server message
(password shorter than 8, bad email); 401 -> "Email or password is wrong". Network failure ->
"Couldn't reach the server. Try again." in `auth-error`. Success: store token, then `GET /me`,
then `location.replace('/')` (full navigation is allowed; it resets nothing important). Cross-link
"New here? Create an account" / "Already have an account? Log in".

### 2.2 `/` Wallet

Left column (money), right column (record); at <= 860 px one column in this order: balance, forms,
feed. The three forms are **always all visible** (no tabs, no collapsed panels: a test must be able to
fill any of them without a click first). Hierarchy instead of hiding: "Send money" is the primary panel
(filled accent button), "Request money" and "Reserve money" are quieter panels (outlined buttons) stacked
below it, each with a one-line explanation ("Reserve: hold money for someone to collect later").

| testid | Presence rule |
|---|---|
| `wallet-available` | after first load; formatted `available`, `data-amount` minor units; the hero |
| `wallet-balance` | after first load; formatted `total`, `data-amount`; secondary line "Total balance" |
| `wallet-held` | after first load **only when `held` > 0**; `data-amount` |
| `wallet-refresh` | always on `/` (disabled while a refresh runs; label stays "Refresh") |
| `pay-handle`, `pay-amount`, `pay-note`, `pay-visibility`, `pay-submit` | always (inputs enabled while loading data) |
| `pay-error` | only after a confirmed refusal; removed on the next submit that sends or on success |
| `pay-uncertain` | only while an unconfirmed outcome exists (nonempty text); removed on successful retry |
| `request-handle`, `request-amount`, `request-note`, `request-submit` | always |
| `request-error` | only after a refusal of the request form |
| `authorize-*` (handle, amount, note, visibility, submit, error) | always (third panel "Reserve money"); same component also mounted on `/authorizations` |
| `activity-list` | when at least one visible payment; children newest first |
| `activity-item-{id}` | per payment, `data-visibility` |
| `activity-parties-{id}` | text "from-handle → to-handle" (contains both) |
| `activity-amount-{id}` | text exactly the formatted amount (no sign, no icon inside the element) |
| `activity-note-{id}` | text exactly the note; element always present, visually collapsed when empty |
| `empty-activity` | instead of the list when nothing visible; text "No payments yet" + hint |

Feed row layout: left a direction chip (arrow glyph + "Sent"/"Received", relative to the caller;
for a public payment between two others "Public"), centre the parties line, the note in quieter text,
a `<time datetime>` with a human string ("Today 14:32", "12 Sep") and a `title` with the exact RFC
3339 string, right the amount (right-aligned, tabular, nowrap). Private rows get the lock chip.
The feed shows the first 50 items (the API default) with a "Show more" button that appends the next
page (`limit`/`offset`, uses `has_more`); a refresh reloads page 1 and collapses to it.

`pay-visibility`: native `<select>` with option values `public` and `private` (labels "Public — anyone
can see it" / "Private — only you and bob"). Default `public`. Same on `authorize-visibility`.

**Pay form behaviour** (state machine in §3.5): amount parsed client-side to minor units; invalid input
-> `pay-error` ("Enter an amount like 15.00") with **no request**. Submitting disables the button and
shows "Sending…". On 2xx: show the success line, **await refresh**, keep the form values, keep the
button enabled. Submitting again unchanged sends nothing (see §3.5) and just re-shows "Already sent.
Change a field to send another payment."; balance falls once, one feed row.

### 2.3 `/requests`

| testid | Presence |
|---|---|
| `incoming-list`, `outgoing-list` | always rendered once loaded (each with a heading "Asked of you" / "You asked"); an empty list shows an inline "None" and the container stays |
| `request-item-{id}` | per request, `data-status` in pending/paid/declined/cancelled |
| `request-amount-{id}` | text exactly the formatted amount |
| `request-pay-{id}`, `request-decline-{id}` | only on a `pending` request where the caller is the payer |
| `request-cancel-{id}` | only on a `pending` request where the caller is the requester |
| `request-error` | after a refused pay/decline/cancel; names the cause; removed on the next action |
| `empty-requests` | when both lists are empty (shown in addition to the two headings, which are hidden then) |
| `wallet-refresh` is not required here; the page offers a "Refresh" link-button (no testid) |

Item: handle of the other party, note, relative time, status badge (icon + word), amount. Pay on a
request: Send privacy choice inline (`<select>`, default public) next to the Pay button, because
visibility is the payer's choice (spec §4). Pay uses an idempotency key per request row (see §3.4);
the visibility choice is part of the body. After success: await refresh of the request list **and**
balance (the header chip area shows the balance in a compact "Available 70.00 EUR" line on every
signed-in screen, without a `wallet-*` testid so `/` stays the only place for those ids). Refusals:
`request_not_pending` -> `request-error` "That request is no longer pending" + refresh (stale pay
button disappears); `insufficient_funds` -> `request-error` "Not enough available funds"; 403 -> "Only
the person asked can pay it". Decline/cancel: no key; 200 refreshes; already-declined is treated as success.

### 2.4 `/split`

| testid | Presence |
|---|---|
| `split-amount`, `split-handles`, `split-note`, `split-submit` | always |
| `split-preview` | always on the page; empty hint until amount and >= 1 handle parse |
| `split-share-{handle}` | one per distinct entered handle, text exactly the formatted share; recomputed on every input event |
| `split-error` | on a refused split (404 unknown handle names the handle) |

Preview uses the §9 rule on BigInt minor units, in handle order. The submitted body is exactly the
parsed values the preview used, and the response's `shares` are compared to the preview: on any
difference the UI shows the server's numbers and a warning (never expected). Success shows "Asked bob
and cy for their share" with a link to `/requests`, and awaits refresh of nothing else on this page
(requests page reloads on visit). The form keeps its values after success; resubmitting unchanged
sends nothing ("Already split") just like pay. Duplicate handles in the field show the one share and an
inline hint, and are sent as typed (the server answers 422, shown in `split-error`).

### 2.5 `/authorizations`

| testid | Presence |
|---|---|
| `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` | always (form at top of page) |
| `authorize-error` | after a refused authorise (insufficient available funds, unknown handle, self) |
| `authorization-list` | when >= 1 authorisation; children newest first |
| `authorization-item-{id}` | `data-status` open/captured/voided/expired |
| `authorization-amount-{id}` | exact formatted authorised amount |
| `authorization-captured-{id}` | only when status is `captured`; exact formatted `captured_amount` |
| `authorization-expires-{id}` | text exactly the RFC 3339 `expires_at` (a separate friendly "expires in 9 min" has no testid) |
| `authorization-capture-amount-{id}` | only on an incoming `open` item; decimal input pre-filled with the remaining amount (e.g. `20.00`) |
| `authorization-capture-{id}` | same condition; button |
| `authorization-void-{id}` | only on an outgoing `open` item |
| `authorization-error` | after a refused capture or void; names the cause |
| `empty-authorizations` | instead of the list when empty |

Extras: on an incoming open item a checkbox "Keep the rest on hold" (`authorization-keep-open-{id}`,
body gets `final:false`). Items show remaining amount ("20.00 EUR still on hold"), capture count, and
for outgoing items who will collect. Capture uses a per-item idempotency key (§3.4); body is
`{amount}` (plus `final:false` when kept open). Refusals map: `authorization_not_open` -> "Already
closed", `authorization_expired` -> "This hold has expired", `capture_exceeds_authorization` -> "That's
more than what's left", `forbidden`. Every refusal refreshes the list and balance. Void: no key,
200 refreshes (a repeated void is success).

### 2.6 Header balance line

On every signed-in screen the header shows a compact "Available 70.00 EUR" (class `.balance-chip`, no
`wallet-*` testid) from the same refresh source, so the number the user can spend is visible after
pay/capture on any screen.

## 3. Client architecture

Files under `stage-2/web/`: `app.html`, `assets/css/tokens.css`, `base.css`, `components.css`,
`screens.css`; `assets/js/app.js` (boot, router), `api.js`, `money.js`, `session.js`, `refresh.js`,
`idem.js`, `dom.js`, `screens/{auth,wallet,requests,split,authorizations}.js`, `forms/{pay,request,
authorize,capture}.js`. No third-party code.

### 3.1 Session and token storage

`localStorage["pocketful.token"]` holds the bearer token (survives reloads and an import: the service
preserves tokens, so the same string stays valid). `session.js` keeps `{token, user}` in memory;
`user` comes from `GET /me`. The client **never discards the token on anything but a 401 from an
authenticated call**; a network error, timeout or 5xx leaves the session intact (an import in progress
can briefly fail a read). On 401: clear storage, `location.replace('/login')`. Logout: `logout-button`
clears storage and goes to `/login` (there is no server logout). `current-user` / `current-handle` are
filled from `/me` once and re-filled by every refresh. Nothing is read from the URL or cookies.

### 3.2 API wrapper (`api.js`)

`api(method, path, {body, key, signal})` -> `{status, body, ok, networkError}`. Always sets
`Accept: application/json` (so `/requests` and `/authorizations` return JSON, not the shell),
`Content-Type: application/json` on bodies, `Authorization`, and `Idempotency-Key` when given.
Timeout 12 s via `AbortController` (the service's own limit is 5 s). A thrown fetch (network down,
abort, connection reset after the server committed) or an unparseable/5xx response resolves to
`{networkError: true}` **for writes** — an *unknown* outcome; for reads it is a plain failure. 4xx with
`{error:{code,message}}` is a **confirmed refusal**; the wrapper never retries by itself.

### 3.3 Money (`money.js`) — integers only

- `parseAmount(text, minorUnits)` -> BigInt minor units or an error code. Trim; accept
  `^\d+$` or `^\d+\.\d+$` (a leading `.5`, `1.`, `-1`, `+1`, `1e3`, `1,5`, spaces inside and the empty
  string are non-numeric). Fraction longer than `minorUnits` digits -> `too_many_decimals`
  (**15.005 is rejected, never rounded**); `minor_units 0` rejects any fraction (`15.0` too). Result =
  whole·10^m + fraction right-padded; no `Number`, no float math. `15` and `15.00` -> `1500n`, `15.5` ->
  `1550n`. Bodies send `Number(minor)` only after checking it is <= 1000000000 (above that: error
  "Amount is too large", no request); the server remains the authority for ranges.
- `formatAmount(minor, minorUnits, currency)` from a `Number|BigInt|string`: digits via BigInt, pad,
  insert the point, `"100.00 EUR"`, `"1200 JPY"`, `"1.234 BHD"`; no grouping separators, no sign (the
  UI never formats negatives; a negative input throws in development). `formatPlain` omits the code
  for input pre-fill (`20.00`).
- Currency and `minor_units` always come from `GET /me`.
- `splitShares(minor, n)`: `base = minor / n`, `rem = minor % n` in BigInt; share i = `base + (i < rem ? 1 : 0)`.
  Matches §9 (`1000/3 -> 334,333,333`; `1/3 -> 1,0,0`; `5/5 -> 1×5`).
- Unit-tested in the browser (`page.evaluate` against `money.js`) with the §9 table, the minor-unit
  0/2/3 cases, 2^53 and 15.005.

### 3.4 Idempotency key lifecycle (`idem.js`)

Every write form owns one `Attempt` object `{fingerprint, key, phase}` in module memory (never
`localStorage`, never cleared by navigation inside the app, never reloaded — the spec asks for no
recovery across reloads). `fingerprint` = the canonical JSON of the **request body that would be
sent** (minor units, normalised handle/note/visibility) plus the path.

- **Submit** builds the body. If `fingerprint === attempt.fingerprint`: phase `succeeded` -> send
  nothing, re-show "Already sent" (§2.2); phase `uncertain` -> **resend with the same key and the
  same body** (a retry); phase `refused` -> new key (a confirmed refusal changed nothing, spec §7 "key
  reused after a 4xx is a first use", but using a fresh key is simpler and safe). A different
  fingerprint -> new key (`crypto.randomUUID()`), phase `idle`.
- Phases: `idle -> inflight -> succeeded | refused | uncertain`. `uncertain` is entered on network
  error, timeout or 5xx for a write; **it is not an error element** (`pay-uncertain`, never
  `pay-error`).
- A **2xx of either kind (201 or the replay's 200) is success**: a retry that the server recognises as
  a replay returns the original body; the UI treats it exactly like first success (refresh, clear
  uncertainty).
- A key survives an export/import upgrade because it lives only in memory and the server preserves
  idempotency records; the retry after the import returns `200` with the original payment.
- Keys: pay (`/payments`), request (`/requests`), split (`/splits`), authorise (`/authorizations`),
  request-row pay (`/requests/{id}/pay`, one `Attempt` per request id), capture (one per authorisation
  id). Decline, cancel and void have no key.
- Editing any field of an `uncertain` form keeps nothing: the next submit is a new payment with a new
  key. The uncertain box is replaced by a quiet note "A previous attempt wasn't confirmed — check
  your activity before sending again" (no `pay-uncertain`), and the feed is refreshed so the user can
  see whether it landed.

### 3.5 Pay form state machine

```
idle --submit(valid)--> inflight --2xx--> refreshing --done--> succeeded   (success line, no errors)
   |                        |--4xx----> refused (pay-error, inputs kept, balance+feed refresh)
   |                        '--net/5xx-> uncertain (pay-uncertain, inputs kept, retry same key)
   '--submit(invalid)--> refused-local (pay-error, NO request)
succeeded --submit(unchanged)--> succeeded (no request)
succeeded|refused|uncertain --edit field--> idle (new key on next submit)
uncertain --submit(unchanged)--> inflight (same key + body)
```

On `refused` after "insufficient funds" caused by another client: `pay-error` shows the server message,
**balance and feed are refreshed**, every input value is preserved. The same machine drives the request,
authorise, split and capture forms with their own testids.

### 3.6 Latest refresh wins (`refresh.js`)

One module-level counter `seq`. `refresh()` does `const mine = ++seq`, fetches `/me` and `/activity`
(and, when on those screens, `/requests` or `/authorizations`) in parallel, and applies the results only
`if (mine === seq)` **after** all resolved; any older response that arrives later is dropped
whole (never half-applied). Failure of the latest refresh leaves the old data and shows "Couldn't
refresh — Try again" in the live region (not a testid). `wallet-refresh` calls `refresh()`; it never
touches the form (values, attempts, errors stay). A successful write calls `await refresh()` and only
then renders its success line, so the balance, feed and lists on screen already show the new state
when the success appears; a write's refresh starts after the write resolved, so it is always newer
than any earlier refresh.

### 3.7 Rendering rules

- Test-id lists are rebuilt by keyed reconciliation (reuse `activity-item-{id}` nodes), newest first,
  the order the API returns (for `/activity`, equal timestamps may swap).
- No layout shift on refresh (rows keep size; skeleton only on first load).
- Focus is never moved by a refresh. After a successful action focus stays on the control that was
  used; after an error focus moves to the error element (`tabindex="-1"`) only for keyboard-submitted forms.

## 4. Seam needed from the builder

1. **HTML routes.** `GET /`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations` return
   `web/app.html` (200, `text/html; charset=utf-8`) when the request `Accept` contains `text/html`.
   `/requests` and `/authorizations` without `text/html` stay JSON (API). `/`, `/split`, `/signup`,
   `/login` have no JSON meaning, so they may return the shell for any `Accept` without a JSON-only
   preference. Shell responses need **no authentication**; trailing slash variants optional. Unknown
   paths keep the JSON 404.
2. **Static assets.** `GET /assets/<path>` serves files from `web/assets/` (no auth), correct
   `Content-Type` (`text/css; charset=utf-8`, `text/javascript; charset=utf-8` for `.js` — ES modules
   require it, `image/svg+xml`, `font/woff2` if ever used), `Content-Length`, HEAD ok,
   `Cache-Control: no-cache`; reject `..` path escapes with 404; 404 JSON for missing files.
3. **Packaging.** `Dockerfile` copies `web/` next to `app/` (e.g. `COPY web/ ./web/`); lookup path
   relative to the app package, not the cwd.
4. **API facts I rely on**: `GET /me` returns `balance`, `total`, `available`, `held`, `currency`,
   `minor_units`, `handle`, `display_name`; `GET /activity`, `GET /requests`, `GET /authorizations`
   return `{payments|requests|authorizations, has_more}`; error bodies per §5; idempotent replays
   `200`; tokens and idempotency records survive `POST /_test/import`.
5. **No `Set-Cookie`, no redirects** from the shell routes; no CSP that forbids same-origin scripts
   and styles (the UI has no inline script or style). A permissive `Content-Security-Policy:
   default-src 'self'` is fine and welcome.

## 5. Work items (designer lane, S2.U1–U7)

| Id | Scope | DONE WHEN |
|---|---|---|
| U1 | `tokens.css`, `base.css`, `components.css`, `app.html` shell, nav (header + mobile tab bar), `dom.js`, `session.js`, router, signup and login screens | `tools/ui_check.py auth` (Playwright, chromium) passes at 390 and 1280 px: sign up -> lands on `/` signed in; login with wrong password shows `auth-error`; `current-user` and `current-handle` (exact handle) visible on every route; `logout-button` signs out; tab key reaches every control with a visible focus ring; `document.documentElement.scrollWidth <= innerWidth`; console has no errors; screenshots in `reviews/stage2/shots/`. |
| U2 | `money.js`, `idem.js`, `refresh.js`, `api.js` + browser unit checks | `tools/ui_check.py units`: §9 table, minor_units 0/2/3 format and parse, `15.005` and `1e3` and `-1` rejected, `15`/`15.00` -> 1500, 2^53 formats and fits one line at 375 px, stale-refresh drop test with out-of-order responses (route delays), key reuse and renewal rules. |
| U3 | `/` screen: balance block, pay and request forms, feed, `wallet-refresh`, loading/empty/error states | `ui_check.py wallet`: every testid of §2.2 per its presence rule; pay once then submit again unchanged -> one POST, balance falls once, one feed row, no `pay-error`; change a field -> second payment; insufficient funds -> `pay-error`, inputs kept, balance refreshed; held > 0 shows `wallet-held`, absent at 0; hero is the largest text on the page (computed font sizes); 390 and 1280 px screenshots of loading, empty, success, refused. |
| U4 | `/requests` screen with pay/decline/cancel, stale-button handling | `ui_check.py requests`: seeded pending incoming and outgoing requests; buttons per presence rules; cancel elsewhere then Pay -> `request-error` and the pay button disappears; pay moves money once; empty state; two statuses visible with icon and word. |
| U5 | `/split` screen with live preview | `ui_check.py split`: preview equals §9 rows for 1000/3, 1/3, 10/3, 999/3, 5/5 and equals the server's response shares; unknown handle -> `split-error`; caller included and omitted; no request until submit. |
| U6 | `/authorizations` screen, authorise form on `/` and here, capture/void | `ui_check.py auth2` (name `holds`): seeded open hold -> `wallet-held` and `wallet-available` right after reset; capture partial, final, keep-open; void; expired shown as expired; refusal mapping for all four codes; `authorization-expires-{id}` text equals the API's `expires_at`. |
| U7 | Competing clients and uncertain outcomes; upgrade across import | `ui_check.py chaos`: second client spends the balance -> refused pay keeps inputs; response dropped after commit (Playwright route fulfils then aborts) -> `pay-uncertain`, retry same key moves money once, both elements gone; export, import and retry after an import -> original payment recovered, balance refreshed, still signed in without reload; out-of-order `wallet-refresh` responses -> last click wins. |
| U8 | Evidence | `ui_check.py all` runs U1–U7 at 390 and 1280 px; screenshots of every screen and state saved under `reviews/stage2/shots/`; keyboard-only walk (tab order, Enter submits, focus ring never lost) and `scrollWidth` check per route; console clean; packet to the verifier with the full revision, states, viewports and shot paths. |

Order: U1 -> U2 -> U3 -> U4 -> U5 -> U6 -> U7 -> U8; U2 can run in parallel with U1. The seam (§4) must
exist before U1's checks; until then I develop against a throwaway static server outside the repo.

## 6. Decision records to write (stage-2/docs/decisions)

- UI-1 Authorise form is mounted on both `/` ("Reserve money" panel) and `/authorizations`: the spec lists its
  testids with the wallet changes and the new route, so both pages carry it (one component).
- UI-2 Unchanged resubmit after success sends nothing (spec: "must not send another payment"); a
  retry after an unknown outcome resends the same key and body.
- UI-3 `wallet-*` ids exist only on `/`; other screens show a compact header balance without them.
- UI-4 Typography is two system stacks (no font files): offline, no licence, no flash of fallback.
- UI-5 No tabs or collapsed panels on `/`: all three forms are visible so every input is fillable without a click first.
