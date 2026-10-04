# D-38 export envelope stage2

**Question.** Does the stage-2 export change track/format_version?

**What the specification says.** Stage 1 §10 requires `track: "pocketful"`, `format_version: 1`; stage 2 adds no new value.

**Choice.** Stage 2 exports `format_version: 1` with an opaque state that also carries authorizations, ttl and a schema marker; import accepts both its own state and the stage-1 service's state (detected by structure/marker), upgrading the latter with no holds and ttl 600.

**Effect on acceptance tests.** Tests assert envelope track/format_version 1 and round trips both ways in.
