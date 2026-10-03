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

## Work items

| Id | Title | Owner | Assigned | Accepted | Verdicts |
|---|---|---|---|---|---|
| S2.0 | Carry forward | builder | 22:56 | yes | ACCEPT 10e5b5e |
| S2.1 | HTML/static seam | builder | 23:03 | yes | ACCEPT ea8913c, ACCEPT ef17a11 (Vary) |
| S2.2 | Holds model | builder | 23:05 | yes | ACCEPT c0df3c8 |
| S2.3 | Authorize + list | builder | 23:05 | yes | ACCEPT 3facf62 |
| S2.4 | Capture + void | builder | 23:05 | yes | ACCEPT 3d926ec |
| S2.5 | Export/import upgrade | builder | 23:05 | yes | ACCEPT 4e4559c |
| S2.U1 | Shell, auth screens | designer | 23:03 | yes | REJECT b776a89, F1/F2 closed at 773f649 |
| S2.U4+U5 | Requests + split | designer | 23:03 | yes | ACCEPT 1ef373b |

## Rejections and what they caught

- S2.U2+U3 @0fa1361 REJECT (verifier): signed-in header overflowed horizontally between 641 px and ~1030 px (Log out off-screen / over the name at 1024) — spec '375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling'. Verifier now walks 768 and 1024 too.

- S2.U1 @b776a89 REJECT (verifier, from screenshots then measured): 'Log out' wrapped to two lines at 375 and 1280 px; brand icon squeezed to 7x22 at 1280 — product/visual direction 'presentation-ready', 'consistent visual system'.

## Gate table at acceptance

| Gate | Result | Evidence |
|---|---|---|

## Wall time
