# Architecture

## Prinsip Desain

1. AI tidak menyentuh filesystem
2. Evidence before assertion
3. Atomic apply
4. Crash-safe journal
5. Remote lease

## Komponen

- autopilot.py — orchestrator
- executor.py — apply operasi
- packages.py — validasi paket
- ui.py — menu + spinner
- cli.py — CLI
- pkgbuild.py — build paket
- control.py — lease management
- warnings.py — klasifikasi warning

## State Machine

IDLE -> SOURCE_APPLIED -> SOURCE_VERIFIED -> REMOTE_SAFEPOINT -> HUMAN_QA -> READY_TO_LOCK -> LOCKED_LOCAL -> LOCKED_REMOTE

Jika verify gagal: WAITING_GPT.

## File Layout

    ~/.expert-workstation/
    ├ active-version
    ├ versions/<ver>/src/xp/
    ├ runs/<run_id>/
    ├ checkpoints/<project_id>/<run_id>/
    ├ control-repo/
    └ config/workstation.json
