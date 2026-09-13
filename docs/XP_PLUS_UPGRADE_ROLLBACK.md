# XP+ Upgrade & Rollback — Stable 2.1.0

## Compatibility authority

- Tested RC source commit: `a86ad4f3a18fd3c6d0c469bfc868115f37447cfb`.
- Stable target: `2.1.0`.
- Existing external identity remains `xp`, `.xp/`, `XP_PKG_*`, and profile/state/protocol v1.
- XP+-09 does **not** activate or rollback the user's real home.
- User-device use of the **public upgrade path** is deferred to user discretion after stable; XP+-10 must still test that public path on a test installation.

## A-RB lifecycle

`activate_candidate()` retains the candidate-match guard. `rollback_to_previous()` is a distinct entry point for the trusted previous installed engine. Both share the private atomic switch path.

After rollback from stable to rc18.3:

- `active-version` = `2.0.0-rc18.3`;
- `previous-version` = `2.1.0`;
- candidate marker = cleared;
- `engine-rollback-journal.jsonl` records the rolled-back-from version, reason, and timestamp.

Rollback hard-stops when the `previous-version` file is absent or when the referenced previous engine directory is missing/incomplete. Metadata switching remains atomic through `os.replace`.

## XP+-10 publication boundary

The stable commit created by XP+-09 is the only taggable commit. XP+-10 may tag `v2.1.0` only after merged source matches that tested commit and the public-path upgrade test passes on a test installation.
