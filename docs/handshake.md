# XP Handshake — Panduan Sambung untuk AI External

Dokumen ini dibuat oleh Expert Workstation (XP) di perangkat user.
Jika Anda AI (GPT/Claude/dll) yang membaca ini: ikuti panduan ini untuk bekerja lewat XP.

## 1. Fakta Lingkungan
- XP version: jalankan `xp version` untuk angka pasti (dokumen ini era rc18.3)
- Platform: Android + Termux
- Folder pantauan paket: ~/storage/downloads/Expert/
- Jika paket mendarat di Download bawaan ponsel, user cukup jalankan: xp sweep

## 2. Aturan Emas
- JANGAN menyuruh user mengedit file project manual sebagai jalur utama.
- Semua perubahan source harus lewat PAKET yang Anda buat.
- Selalu sertakan human_qa_checklist agar user bisa memverifikasi.
- Batasi scope perubahan dengan allowed_paths.

## 3. Struktur Spec (inti paket)
{
  "spec_version": "1.0",
  "project_id": "<id dari xp project list>",
  "milestone": "<NAMA-MILESTONE>",
  "package_type": "WORK",
  "allowed_paths": ["src/", "supabase/"],
  "operations": [
    {"op": "ADD_FILE", "path": "src/x.py", "mode": "0644", "content": "..."},
    {"op": "REPLACE_FILE", "path": "src/y.py", "mode": "0644", "content": "..."},
    {"op": "DELETE_FILE", "path": "src/z.py"}
  ],
  "human_qa_checklist": ["...", "..."]
}
Build paket di repo project:
  xp pkg-build --repo . --spec <path spec.json>
Hasil: ~/storage/downloads/Expert/XP_PKG_WORK_<project>_<milestone>_<ts>.zip
Jika Anda tidak bisa menjalankan perintah di perangkat user, kirim spec.json
sebagai lampiran; user yang menjalankan pkg-build.

## 4. Alur Setelah Paket Ada
1. User: xp → pilih [2] Scan hasil GPT terbaru
2. XP: verify gate sesuai policies project
3. XP: remote safepoint (push branch kerja)
4. User: QA manual sesuai checklist → QA CLEAR
5. XP: Final Lock → checkpoint terkunci
6. Jika verify gagal: XP rollback + buat XP_GPT_INCIDENT_*.zip → user lampirkan
   ke Anda; Anda balas dengan paket REMEDIATION yang merujuk incident_id.

## 5. Nama File yang XP Kenali
- XP_PKG_WORK_*.zip / XP_PKG_REMEDIATION_*.zip → paket eksekusi
- XP_GPT_INCIDENT_*.zip  → laporan kegagalan untuk Anda
- XP_GPT_BOOTSTRAP_*.zip → handoff onboarding project baru
- XP_BUNDLE_*.txt        → context bundle lintas sesi AI

## 6. Command yang Boleh Anda Minta User Jalankan
xp version | xp help <topik> | xp check | xp sweep | xp project list |
xp project switch <id> | xp project onboard <path> | xp bundle --repo <path> |
xp pkg-build --repo . --spec <file>

## 7. Mulai Bekerja: 3 Permintaan ke User
1. Jalankan `xp project list` — project mana yang kita kerjakan?
2. Jalankan `xp` → [5] Status & audit — milestone terakhir apa yang terkunci?
3. Jalankan `xp bundle --repo <path project>` — lampirkan bundle ke saya.
Setelah itu kirim spec.json pertama Anda. Selamat bekerja.
