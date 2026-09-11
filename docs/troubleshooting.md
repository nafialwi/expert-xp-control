# Troubleshooting

## ANCHOR GAGAL saat patch
Jangan panik — rc sebelumnya tetap aktif. Kirim error ke AI, minta patch versi line-by-line.

## Source verification gagal
XP otomatis rollback. Kirim incident handoff (`~/storage/downloads/Expert/XP_GPT_INCIDENT_*.zip`) ke AI, minta spec REMEDIATION.

## Base source mismatch
Pastikan branch benar dan `git status` bersih.

## Workflow state mismatch
Upgrade ke rc11+ (bug sudah diperbaiki).

## Prettier menolak markdown AI
Jalankan `npx prettier --write <file>`, build REMEDIATION kosong, scan.

## Final Lock hang
Upgrade ke rc10+ (sudah ada spinner). Tunggu 1-3 menit.

## Bundle terlalu besar
Lampirkan file sebagai attachment, jangan paste manual.

## Control repo tidak sync
```bash
cd ~/.expert-workstation/control-repo && git pull
```
