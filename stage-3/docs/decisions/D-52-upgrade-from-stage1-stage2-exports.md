# D-52 upgrade from stage1 stage2 exports

**Question.** How a stage-3 service imports populated stage-1 and stage-2 exports. (open question 9)

**What the specification says.** "A stage-3 service must accept exports produced by the same team's stage-1 or stage-2 service. The ledger must import and account for authorizations and captures. Captures are immutable linked payments".

**Choice.** Detection by state structure (stage-1: no authorizations/settings; stage-2: no revisions). For every imported payment: revision 1 = {amount, effective_at = recorded_at = created_at, reason ""} (settlement members' created_at is their committed_at already). Links: settlement_id → member (immutable); authorization_id → capture (immutable).
Openings: opening(u) = imported balance(u) − net of all imported payments touching u (history rebuilt from revision 1s). No history validation on import (the source service enforced its own rules); an imported history that is negative somewhere is reported as is; corrections touching that user are judged by D-53 on the full corrected history (so they are refused while such a boundary exists). Valid source services cannot produce this.
Authorizations (stage-2): created_at as exported; captures at their payment created_at; open → closed_at null; captured → closed_at = last capture's created_at; expired → closed_at = expires_at; voided → void time is not in a stage-2 export: closed_at = last capture's created_at if any, else created_at (the only choice that cannot make past `available` negative).
Everything else carried: tokens (and the L5 session rule extended: importing a stage-1 OR stage-2 export keeps destination tokens whose user id, email and handle exist in the imported state; a stage-3 export is pure replacement), idempotency receipts of all older paths (replay 200 verbatim), requests, splits, operators, ttl, id counters.
Stage-3 export: format_version 1 envelope (stage 1 §10), state includes revisions, recorded times, closed_at, openings and snapshots; round-trips exactly.

**Effect on acceptance tests.** Tests import real populated exports from the frozen stage-1 and stage-2 images.
