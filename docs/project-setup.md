# Project Setup

## Buat Project Baru

1. Buat repo Git:
```bash
mkdir -p ~/WORKSTATION/projects/my-project
cd ~/WORKSTATION/projects/my-project
git init
```

2. Buat struktur `.xp/` dengan 3 file:
- `.xp/project.json` (project_id, name, adapters, metadata)
- `.xp/policies.json` (branch policy, verify script, warnings)
- `.xp/compatibility.json` (min_xp_version, required commands)

3. Buat `scripts/verify.mjs` berisi daftar gate kanonik.

4. Daftarkan:
```bash
xp
```
Pilih [3] Pilih project lain → register project.

## Daftarkan Repo Existing
```bash
xp
```
Pilih [3] → masukkan path repo.
