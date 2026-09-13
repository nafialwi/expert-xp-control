# XP+-09 XP+ Stable — Execution Plan

**Goal:** satisfy Task 14 and Qwen S1-S8 without changing the user's real active engine.

**Baseline:** `a86ad4f` (`2.1.0-rc1`) on `work/xp-plus-v1`.

## Ordering

1. Deliver/rerun S1 exact rollback/mismatch/atomic tests.
2. Run full RC regression.
3. Run the §14 fixture matrix and installed-candidate A+ Legacy/Next shadow.
4. Run copy-home drill only; never activate/rollback real home.
5. Run clean install from exact RC commit `a86ad4f`.
6. Build an ephemeral `2.1.0` projection from that exact RC source and prove rc18.3 -> 2.1.0 -> rc18.3 in a temp home.
7. Run failed-candidate automatic rollback tests from the **installed projected candidate artifact**.
8. Generate `XP_PLUS_COMPATIBILITY_MATRIX.md` with commit hashes + UTC timestamps and Zone 1/Zone 2 columns.
9. Generate upgrade/rollback documentation and re-run handshake schema generator; require zero handshake diff.
10. Commit evidence/docs while version is still `2.1.0-rc1`.
11. Only after all gates are green, perform the single stable version flip to `2.1.0`, update stable identity expectation + changelog, run full regression, and create the only taggable XP+-09 stable commit.
12. Fresh-install the committed stable source, rerun version/schema/self-test, push, and prove real active XP metadata remained byte-identical.

## Stop gates

Stop and rollback to `a86ad4f` on any v1-readability failure, schema/package drift, source mutation, candidate pre-validation activation, failed rollback, production call, handshake drift, or real-home lifecycle mutation.
