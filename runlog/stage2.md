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

- Final pre-gate (analyst, image 7a15976): event checker stage 1 147/147, stage 2 35/35, 'claimed stage: 2'. Carried stage 1 422/0/3. Stage 2: all green except NEW finding R2-PAY.8 (edit during in-flight submit loses next click) -> S2.U11; 4 upgrade failures were cross-seat interference on a shared stage-1 container (pass alone 7/7).

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
| S2.U1 | Shell, auth screens | designer | 23:03 | yes | REJECT b776a89, ACCEPT 773f649+b0aae37 |
| S2.U2+U3 | Client core + wallet | designer | 23:03 | yes | REJECT 0fa1361, ACCEPT b0aae37 (+0259400) |
| S2.U4+U5 | Requests + split | designer | 23:03 | yes | ACCEPT 1ef373b |
| S2.U6 | Authorizations screen | designer | 23:03 | yes | ACCEPT 3dbd491 |
| S2.U7 | Competing clients, uncertain, upgrade | designer | 23:03 | yes | ACCEPT 46b6e6f |
| S2.U9 | /signup,/login reachable while signed in | designer | 23:3x | yes | ACCEPT 77250c4 |
| S2.8 | Upgrade sessions (L5), ttl, pay replay | builder | 23:5x | yes | ACCEPT bf2e57d |
| S2.U10 | Plan-gate UI fixes | designer | 23:5x | yes | REJECT 74d83a5, closed by S2.U11 8fda234 |
| S2.U11 | Lost click / feedback under tab bar | designer | 00:0x | yes | REJECT c6a8996, ACCEPT 8fda234 |
| S2.9 | Stage 2 RUN.md (gate F6) | builder | 00:5x | yes (in re-gate) | ACCEPT 9fd9c2e via GATE-6a3fd33 |
| S2.5A | Import hold check | builder | 23:2x | yes | ACCEPT eab708e |

## Rejections and what they caught

- Stage gate @6c295d6 REJECT: stage-2/RUN.md still described and built stage 1 (stage 1 §2 RUN.md command). No item review looked at RUN.md after the carry-forward.

- S2.U11 @c6a8996 REJECT (verifier, real-viewport screenshot): with feedback moved below the button, a refused payment's pay-error rendered fully under the fixed bottom tab bar at 390x844 — 'A refused payment shows pay-error'. DOM visibility checks could not see it.

- S2.U10 @74d83a5 REJECT (verifier): new 'change' listener cleared the feedback slot above the submit button on blur, the button jumped and the click was lost after an edit — 'Changing a field makes the next submission a new payment request'. Analyst found the in-flight variant independently (S2.U11).

- S2.U2+U3 @0fa1361 REJECT (verifier): signed-in header overflowed horizontally between 641 px and ~1030 px (Log out off-screen / over the name at 1024) — spec '375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling'. Verifier now walks 768 and 1024 too.

- S2.U1 @b776a89 REJECT (verifier, from screenshots then measured): 'Log out' wrapped to two lines at 375 and 1280 px; brand icon squeezed to 7x22 at 1280 — product/visual direction 'presentation-ready', 'consistent visual system'.

## Stage gate

- Gate packet sent on 6c295d6fb5f0d1b178b9c3597a3a9da97e59a9de (stage 2 spec pasted 3 parts + packet); seats told to quiet host.

- Gate 1 on 6c295d6: REJECT (verifier) on F6 only — stage-2/RUN.md was the unchanged stage-1 copy (title, command building stage-1, stale soak path). G1-G6, G8 green; G7 red on F6. -> S2.9 builder.

## Gate table at acceptance

Stage 2 ACCEPTED at 6a3fd334b9a64588b9d821ba654ae47538cba7bc (re-gate; verdict reviews/stage2/GATE-6a3fd33.md, commit 7c208ba). First gate attempt 6c295d6 rejected on F6 (stale RUN.md) only.

| Gate | Result | Evidence |
|---|---|---|
| G1 Ledger | green | 182 R2 rows + 21 changed stage-1 rows, 0 blank cells |
| G2 Plan | green | plan.md + ui-plan.md, analyst round 1, lead decision L6 |
| G3 Acceptance (stage 2) | green | acceptance/stage2: 272 passed |
| G4 Chain (stage 1) | green | acceptance/stage1 vs stage-2 container: 422 passed, 3 skipped; ACCEPTANCE_DOCKER 4 passed |
| G5 Supplied checker | green | checks/s2-gate2-verifier-200816: stage 1 pass, stage 2 pass, "claimed stage: 2 on the shipped checks" (stage 3 fail expected) |
| G6 Invariants | green | stress 60 s 8/8, 27746 reqs, 0 5xx; holds_stress 60 s 193592 ops max 0.125 s; soak max 1.93 s, nr_throttled 0; 2000-user reset 1.51 s; burst max 1.06 s |
| G7 Review | green | standards + spec; no CDN/runtime network, CSP self, Vary: Accept, upgrade path; RUN.md both commands run and start stage 2 |
| G8 User facing | green | walker 46 states x 5 widths (375/390/768/1024/1280) = 230/230 clean; 265/265 browser scenarios; 90/90 feedback visible; screenshots reviews/stage2/shots/GATE-6c295d6/ judged against product direction |

## Wall time

Dispatch 22:54:33Z -> re-gate ACCEPT ~01:09Z: about 2 h 15 min. Item rejections: 4 (S2.U1 b776a89, S2.U2+U3 0fa1361, S2.U10 74d83a5, S2.U11 c6a8996), all designer, all caught from real-browser screenshots or measurement. Stage gate failures: 1 of 3 (6c295d6, stale RUN.md).

## Findings caught beyond item reviews

- Event checker run 1 (builder): /signup and /login redirected signed-in users -> S2.U9.
- Analyst plan gate: browser session lost across a stage-1 import (D-22 -> L5, S2.8); edit-then-revert not a new key; split parsing; ttl cap.
- Analyst acceptance: wallet-refresh disabled during refresh broke latest-refresh-wins; edit during in-flight submit lost the next click (S2.U11).
- Verifier stage gate: stage-2/RUN.md still the stage-1 copy.

## Decisions

- L4 build before plan gate; L5 stage-1 upgrade keeps matching destination sessions (stage 2 overrides stage 1 §10 for the upgrade path only); L6 plan gate closed after one round. Details in runlog/state.md.

## Open risks

- L5 widens session survival on a stage-1-format import to destination tokens whose user matches id, email and handle; a stage-2 import stays pure replacement.
- Pre-upgrade replays return stored stage-1 bodies without authorization_id (D11/D-34), per stage 1 §7 'body identical to the original response'.
- Fonts are system stacks (no font files shipped); look varies slightly per OS.
- scrypt costs from stage 1 (N=2^13 signup, 2^9 seeded) carried unchanged.
