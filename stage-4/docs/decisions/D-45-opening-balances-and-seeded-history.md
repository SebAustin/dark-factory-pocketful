# D-45 opening balances and seeded history

**Question.** How are wallet opening balances defined for seeded, signed-up and imported users, and is seeded history validated?

**What the specification says.** "Opening balances equal seeded ending balances minus the net effect of original seeded payments. Corrections must not change those opening balances. New accounts open at zero. Seeded history is consistent and nonnegative."

**Choice.** opening(u) = seeded balance(u) − Σ(original seeded amounts received by u) + Σ(original seeded amounts sent by u); signed-up users 0; imported users D-52. The opening is a fixed per-user constant from that moment: corrections change later balances by moving money at their effective time, never the opening. Balance(u, T, K) = opening(u) + Σ signed selected amounts with effective_at ≤ T.
Reset validates the seeded history: every user's opening ≥ 0 and the balance after every seeded boundary ≥ 0 (with same-instant payments combined), and seeded open holds within total at their creation (stage 2 over-balance rule, evaluated at R). A violation → 422 validation_failed, nothing changes. (The spec promises consistency; rejecting inconsistent input is the conservative reading and keeps R3-INV.2.)

**Effect on acceptance tests.** Tests: R3-ME.7 opening; R3-REV.5 corrections keep opening; R3-TS.9 negative opening → 422.
