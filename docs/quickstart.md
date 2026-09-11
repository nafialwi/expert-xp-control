# Quick Start

Expert Workstation (XP) adalah framework untuk membangun project dengan disiplin checkpoint, verifikasi otomatis, dan audit trail.

## Prasyarat
- Termux (Android)
- Python 3.10+
- Node.js 18+
- Git
- psql (PostgreSQL client)

## Install
```bash
curl -fsSL https://raw.githubusercontent.com/nafialwi/expert-xp-control/xp-engine/installer.sh | sh
```

## Mulai
```bash
xp help
```

## Alur Kerja
1. AI mengirim spec.json (blueprint deklaratif)
2. User build: `xp pkg-build --repo <path> --spec <spec.json>`
3. User scan di menu XP: pilih [2]
4. XP apply + verify + safepoint
5. User QA manual
6. Final Lock → checkpoint terkunci
