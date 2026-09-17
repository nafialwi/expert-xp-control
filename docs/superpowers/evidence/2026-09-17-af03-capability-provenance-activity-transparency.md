# AF-03 Verification Evidence

Date: 2026-09-17

## Identity

- Branch: `work/af03-capability-transparency`
- AF-03 implementation head: `0cac7f390c0474b6d3486d4014bab74bb11586ec`
- Evidence base HEAD after Spec/Plan commit: `2a45782cfde2efe5316f7023324c7d61f5144216`
- AF-02 base used for protected-scope comparison: `9ed7392`

## AF-03 implementation commits

- `6d8fbff` feat(af03): add canonical capability state
- `1c3d1ac` feat(af03): add explicit live capability checks
- `da8b5f5` feat(af03): add persistent activity trails
- `ad87ecd` feat(af03): record ai and agent provenance
- `18242a6` feat(af03): expose live check and activity history
- `0cac7f3` feat(af03): record objective activity metrics
- `2a45782` docs(af03): lock capability transparency spec and plan

## Verification results

- Dedicated AF-03: **Ran 34 tests in 0.070s — OK**
- Task 6 objective-metrics boundary: **Ran 2 tests in 0.544s — OK**
- AF-02 AI regression: **Ran 47 tests in 0.012s — OK**
- Core safety/compatibility regression: **Ran 32 tests in 1.204s — OK**
- Task 7 original full regression: **Ran 182 tests in 15.782s — OK (skipped=1)**
- Final fresh full regression after documentation recovery: **Ran 182 tests in 16.186s — OK (skipped=1)**
- Offline tripwire: **Ran 1 test in 0.012s — OK**
- Secret/history sanitizer regression: **Ran 1 test in 0.002s — OK**

## Offline and explicit Live Check invariants

Plain `xp check` produced:

- `Mode: LOCAL/OFFLINE`
- `Live Check: Belum diperiksa`
- no `Mode: LIVE` marker.

Assertion results:

- LOCAL/OFFLINE marker grep exit: `0`
- NOT_CHECKED marker grep exit: `0`
- LIVE marker grep exit: `1` — expected `1`, proving LIVE mode was absent.

The AF-03 offline tripwire passed. Normal checks therefore do not construct or invoke the Live Check service. Live probing remains explicit-only.

## No silent fallback

The dedicated AF-02/AF-03 gateway regression passed, including the explicit test that a selected-route failure is surfaced rather than automatically switching to another route.

No alternate provider is silently selected by AF-03.

## Provenance and activity safety

AF-03 keeps source, processor/model, and via/tool route as separate provenance fields.

The Activity Trail persists observable actions and results only. It does not persist hidden chain-of-thought.

The prohibited-field scan found textual occurrences of:

- `chain_of_thought`
- `scratchpad`
- `reasoning_content`

only in the sanitizer deny-list/docstring and test fixtures/assertions used to prove rejection/redaction. They are not persisted ActivityEvent schema fields.

Synthetic secret and hidden-reasoning values passed through the production sanitizer regression and were confirmed absent from persisted activity history.

## Objective metrics

Source verification records objective step results from already-known execution outcomes:

- passed,
- failed,
- skipped.

These counts are derived from executed verification-step outcomes/return codes and control flow, not by parsing model reasoning or terminal prose.

## Protected-scope inspection

Compared with AF-02 base `9ed7392`:

- `src/xp/adapters/generic.py`
- `src/xp/executor.py`
- `src/xp/workflow.py`
- `src/xp/config.py`

Protected-scope diff lines: **0**.

Comparison against `v2.1.0` protected scope: **0** diff lines.

No AF-03 behavioral redesign was introduced in these protected components.

## Anti-fake-success confirmations

AF-03 preserves these rules:

- Unknown != Success
- Not Checked != Available
- Requested != Completed
- Started != Completed
- AI Generated != Live
- Fallback != Original Provider

Runtime failures are surfaced as failure or Perlu perhatian rather than represented as success.

## Completion gate

Task 7 evidence is acceptable only if:

- all regression commands above are green,
- final full regression exit is 0,
- plain check remains offline,
- no silent fallback test passes,
- secret/history sanitizer test passes,
- protected-scope diff remains clean,
- Spec and Plan are committed,
- final evidence commit succeeds,
- final worktree is clean.
