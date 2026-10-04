# Verifier stage 3 tools

- `upgrade_driver.py populate --s1 <frozen stage-1 url> --s2 <frozen stage-2 url> --out DIR`: fills each source with rich state, then exports it.
  The state covers a seeded payment, same-second payment bursts, private payments, requests paid/declined/cancelled/pending, a zero-share
  split with its 0 request paid, an operator settlement, a failed key, a signup user, and (stage 2) holds captured partially, an extended capture
  chain, voided, expired and open. It writes `<stage>.export.json` and `<stage>.meta.json` (tokens, idempotent bodies with their original
  responses, balances, settlement members, capture ids).
- `upgrade_driver.py check --s3 <stage-3 url> --out DIR`: imports each export into stage 3 and checks:
  - tokens still authenticate; totals equal the source balances; every idempotent write replays its original body; failed keys are reusable;
  - per-user `/statement` (all pages, by snapshot): opening + deltas = closing = current, chained, ordered;
  - the sum of balances = the seeded total in `/me?as_of=` at every entry instant;
  - settlement members and captures → 422 `linked_payment_immutable`;
  - an ordinary correction → 201 with an identical 200 replay; revisions start at 1 with reason "".
- `hist_probe.py <stage-3 url>` (`HIST_SECONDS`, default 30): 20 writers (payments, corrections with expected_revision, authorizations
  and captures) run alongside 10 readers. Each `/me?as_of=K&known_at=K` view over all users must sum to the seeded total with the
  balance/total/available/held identities. A frozen past view must never change. Statements must chain, and snapshot pages (limit 3) must equal the
  frozen first read. Afterwards it checks a 20-way same-expected_revision correction race (exactly one 201). It fails on any 5xx or > 5 s response.

Smoke-tested against the stage-3 copy (stage-2 code): the stage-1/2 parts pass; the stage-3 endpoints are absent (404), as expected before S3 items land.
Frozen source images: stage 1 = tag `verifier-gate` (9d7ab5e), stage 2 = tag `verifier-gate3` (6a3fd33).
