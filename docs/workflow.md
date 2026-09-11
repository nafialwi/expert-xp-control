# Workflow

## Siklus Paket WORK
`spec.json → pkg-build → scan [2] → apply → verify → safepoint → HUMAN_QA → FINAL_LOCK`

### 1. AI mengirim spec.json
Spec adalah blueprint deklaratif dengan field:
- `package_type`: WORK atau REMEDIATION
- `milestone`: nama milestone
- `allowed_paths`: scope file yang boleh diubah
- `human_qa`: checklist verifikasi manual
- `operations`: daftar operasi (ADD_FILE, REPLACE_FILE)

### 2. Build paket
```bash
xp pkg-build --repo <path> --spec <spec.json>
```

### 3. Scan di menu XP
```bash
xp
```
Pilih [2] → pilih paket → tunggu verify.

### 4. Apply + Verify
XP otomatis: validasi fingerprint, terapkan operasi (atomic), jalankan gate (repo-guard → format → lint → typecheck → test → build → diff-check), safepoint (commit + push).

### 5. HUMAN_QA
XP berhenti, menunggu review manual.

### 6. FINAL_LOCK
XP buat checkpoint artifact (CHECKPOINT.md, SOURCE.zip, SHA256SUMS.txt, CHECKPOINT_STATE.json).

## Siklus REMEDIATION
Jika verify gagal: XP rollback, buat incident handoff, AI kirim spec REMEDIATION, build + scan → XP lanjutkan dari WAITING_GPT.
