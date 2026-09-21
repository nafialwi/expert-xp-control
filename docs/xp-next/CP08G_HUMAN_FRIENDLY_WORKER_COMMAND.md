# CP-08G — Human-Friendly Worker Command Flow

Status: PASS

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 1dc7a760ce1b55ab4d9618bd700feec2ad94707c
- CP-08F worker recommendation + confirmation integration: PASS
- stable XP 2.1.0 source: untouched

## Goal

Expose the CP-08E/CP-08F worker recommendation and confirmation contract through
the XP Next command surface without requiring callers to assemble internal
Python objects.

The command must preserve explicit human confirmation and no-silent-switch
behavior. CP-08G does not add automatic worker execution to the CLI.

## Command surface

XP Next now exposes:

`xp-next worker choose`

The command accepts either:

- `--prompt <text>`; or
- `--prompt-file <local UTF-8 file>`.

Optional controls:

- `--backend lightweight_local|hermes` requests one exact backend;
- `--confirm` explicitly confirms the displayed backend;
- `--decline` explicitly declines it;
- `--json` emits structured selection/confirmation records;
- Hermes binary, loopback URL, and model can be overridden explicitly.

Without `--confirm` or `--decline`, an interactive terminal shows a small menu:

- `[1] Gunakan <worker>`
- `[0] Batal`

In a non-interactive session, absence of an explicit decision returns a distinct
confirmation-required exit code. XP does not auto-confirm.

## Human-readable view

The default output shows:

- whether the worker is recommended, explicitly selected, or unavailable;
- worker backend name;
- selection reason;
- observed available memory;
- logical CPU count;
- whether confirmation is required;
- explicit use/cancel choices.

A successful confirmation is displayed separately from the recommendation so a
recommendation cannot be mistaken for execution approval.

## No-silent-switch behavior

An explicit incompatible backend still fails closed.

Example:

- user requests `lightweight_local`;
- prompt is not a valid bounded lightweight operation;
- result: worker unavailable / NEEDS_ATTENTION;
- no Hermes fallback is attempted.

The command delegates actual confirmation to CP-08F, which performs a fresh
resource/readiness recheck before producing CONFIRMED.

## Real PC smoke

The real CLI surface was exercised through `pc-xpnext` using the actual WSL
resource probe and a bounded `replace_text` operation.

Observed during the successful smoke run:

- available memory: 1206 MiB;
- logical CPUs: 4;
- recommendation: lightweight_local;
- human-equivalent CLI confirmation: explicit `--confirm`;
- result: CONFIRMED;
- Git working-tree state before and after the command was identical.

The CLI did not execute a filesystem worker or mutate an original project; this
checkpoint covers human-facing selection/confirmation only.

## Acceptance evidence

Targeted CLI/UI/selection/E2E suite:
- 29 tests PASS.

Full XP Next regression:
- 135 tests PASS;
- zero test failures;
- `git diff --check` PASS.

New coverage verifies:

- human-readable recommendation text includes worker, reason, resources, and
  explicit choices;
- explicit confirmation produces a distinct CONFIRMED view;
- explicit decline produces a distinct cancellation result;
- non-interactive use without a decision never auto-confirms;
- explicit incompatible worker requests still fail without fallback;
- prompt files are supported;
- JSON mode remains machine-readable for future orchestration.

## Development/audit evidence

The first broad CP-08G preflight audit job returned a nonzero shell status after
its discovery section even though branch/HEAD/clean checks and the baseline test
suite had completed successfully. A smaller focused CLI audit was run and
passed before any implementation work continued.

The first real CLI smoke command also returned nonzero because the smoke script
incorrectly asserted that the repository must be clean while CP-08G changes
were intentionally still uncommitted. The CLI itself had already produced the
correct recommendation and confirmation. The smoke was corrected to compare
Git state before vs. after the CLI call; the second run passed and proved the
command introduced no additional source mutation.

No failed run was accepted as checkpoint evidence.

## Safety boundaries

CP-08G does not:

- auto-confirm recommendations;
- execute a worker from the human-facing chooser;
- silently change worker/provider;
- translate prose into lightweight filesystem operations;
- apply sandbox changes;
- deploy;
- migrate production data;
- touch Segeran Jiwa projects;
- require paid API, cloud AI, or 9Router;
- weaken CP-08F exact-backend binding, review, recovery, rollback, or
  post-Apply verification.

## Remaining work

The worker choice is now understandable from the CLI, but a user still needs a
separate higher-level work command to carry a confirmed choice into the full
job lifecycle without manually composing low-level arguments.

A following bounded checkpoint should add a small human-facing `work` flow that
creates/resumes a job and connects the existing project context, worker choice,
approval, sandbox execution, review, and Apply controls without bypassing any
current safety gate.
