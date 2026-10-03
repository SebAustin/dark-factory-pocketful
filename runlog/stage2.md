# Stage 2 run log: pocketful wallet screens and payment authorizations

- Dispatch: 2026-10-03T22:54:33Z (one human message; no further human input)
- Specification: pocketful/spec/stage-2.md (verbatim copy in runlog/stage2-spec.md); stage-1.md still applies (runlog/stage1-spec.md)
- Stage folder: stage-2/ (carried from stage-1 accepted at 9d7ab5e; stage-1/ frozen)

## Timeline

| Time (UTC) | Event |
|---|---|
| 22:54 | Dispatch received; seats present from stage 1 |
| 22:56 | S2.0 carry-forward -> builder; stage 2 spec (3 parts) + S2.L ledger -> analyst, S2.P API plan -> builder, S2.U UI plan -> designer |
| 22:58 | S2.0 committed 10e5b5e; review + screen tooling -> verifier |

## Early signals

- Event checker run 1 (builder, isolated, rev 3dbd491): stage 1 pass; stage 2 33/35 — 2 failures: /signup and /login redirect a signed-in user (UI) -> S2.U9.

- Acceptance re-run (analyst, image 79a7bf6, tests 29db0cd): carried stage 1 422 passed/0 failed/3 skipped; stage 2 262/268 — 4 await S2.8 (D-22), 2 = refresh button disabled during refresh (R2-RACE.2) -> S2.U10.

## Plan gate

Round 1 (analyst): 1 blocking (D-22 browser session across stage-1 import -> lead ruling L5) + 5 minor. Lead decision L6: gate closed; findings -> S2.8 (builder), S2.U10 (designer), or already satisfied.

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S2.0 | Carry forward | builder | 22:56 | yes | ACCEPT 10e5b5e |
| S2.1 | HTML/static seam | builder | 23:03 | yes | ACCEPT ea8913c, ACCEPT ef17a11 (Vary) |
| S2.2 | Holds model | builder | 23:05 | yes | ACCEPT c0df3c8 |
| S2.3 | Authorize + list | builder | 23:05 | yes | ACCEPT 3facf62 |
| S2.4 | Capture + void | builder | 23:05 | yes | ACCEPT 3d926ec |
| S2.5 | Export/import upgrade | builder | 23:05 | yes | ACCEPT 4e4559c |
| S2.6 | Holds concurrency/load | builder | 23:05 | yes | ACCEPT 0c72f1f |
| S2.U1 | Shell, auth screens | designer | 23:03 | yes | REJECT b776a89, F1/F2 closed at 773f649 |
| S2.U4+U5 | Requests + split | designer | 23:03 | yes | ACCEPT 1ef373b |
| S2.U6 | Authorizations screen | designer | 23:03 | yes | ACCEPT 3dbd491 |
| S2.U7 | Competing clients, uncertain, upgrade | designer | 23:03 | yes | ACCEPT 46b6e6f |
| S2.U9 | /signup,/login reachable while signed in | designer | 23:3x | yes | ACCEPT 77250c4 |
| S2.5A | Import hold check | builder | 23:2x | yes | ACCEPT eab708e |

## Rejections and what they caught

- S2.U2+U3 @0fa1361 REJECT (verifier): signed-in header overflowed horizontally between 641 px and ~1030 px (Log out off-screen / over the name at 1024) — spec '375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling'. Verifier now walks 768 and 1024 too.

- S2.U1 @b776a89 REJECT (verifier, from screenshots then measured): 'Log out' wrapped to two lines at 375 and 1280 px; brand icon squeezed to 7x22 at 1280 — product/visual direction 'presentation-ready', 'consistent visual system'.

## Gate table at acceptance

| Gate | Result | Evidence |
|---|---|---|

## Wall time
