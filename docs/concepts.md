# Concepts

## Checkpoint
Arsip permanen milestone terkunci. Berisi: CHECKPOINT.md, CHECKPOINT_STATE.json, SOURCE.zip, SHA256SUMS.txt. Lokasi: `~/.expert-workstation/checkpoints/<project_id>/<run_id>/`

## Run
Eksekusi satu paket. Punya run_id, milestone, stage, journal.

## Safepoint
Commit otomatis ke branch kerja setelah verify lolos.

## Lease
Mekanisme koordinasi multi-device di control-repo.

## Fingerprint
Hash source saat paket di-build. Mismatch = paket ditolak.

## Allowed Paths
Scope file yang boleh diubah. Operasi di luar scope ditolak.

## Gate
8 rantai verifikasi: repo-guard, format:check, lint, typecheck, test:js, test:py, build, diff-check.

## Incident
State saat verify gagal. XP rollback + buat incident handoff.

## Human QA
Gerbang manual setelah verify lolos.

## Final Lock
Proses penguncian milestone: final verify → checkpoint → commit lock → push → rilis lease.
