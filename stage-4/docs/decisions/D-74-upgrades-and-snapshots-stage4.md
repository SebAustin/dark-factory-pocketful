# D-74 upgrades and snapshots stage4

**Question.** Upgrades from stages 1–3 and snapshots in stage-4 exports. (open point 10, lead L10)

**What the specification says.** "A stage-4 service must accept exports produced by the same team's stages 1–3, retaining settlement membership, corrections and snapshots."

**Choice.** Stage-1/2 exports: as D-52 (revision 1 synthesised, openings derived, holds timed), plus refund_of null, no batches. Stage-3 exports: revisions, recorded times, closed_at, memberships kept verbatim; correction_batch_id null on every imported revision. Sessions: the L5 rule (keep matching destination tokens) applies to stage-1/2/3 exports; a stage-4 export is pure replacement.
Snapshots (L10, L12): stage-4 exports include every snapshot token with its frozen result. Importing a stage-4 export MERGES them into the in-process store: imported tokens are added (an imported token wins on a token collision) and every existing destination token keeps paging. So a token minted before an export pages identically after importing that export (even after a reset in between), and a destination token minted before the import still pages after it. Reset clears every token. Importing a stage-1/2/3 export adds no tokens and leaves the store untouched. Known limitation (recorded, not worked around): frozen stage-3 exports carry no snapshots (L8), so stage-3 tokens cannot survive an upgrade.

**Effect on acceptance tests.** Round-trip test for stage-4 snapshots; upgrade tests from real frozen stage-1/2/3 images.
