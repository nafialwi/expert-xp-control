# Expert Workstation (XP)

Framework untuk membangun project dengan disiplin checkpoint, verifikasi otomatis, dan audit trail.

## Visi

XP adalah "rumah" untuk project-project Anda. AI mengirim blueprint deklaratif, XP execute dengan safety gates. Hasilnya: milestone terkunci dengan bukti yang bisa diverifikasi kapan pun.

## Fitur

- Checkpoint System (arsip permanen milestone)
- 8 Gate Verification (lint, test, build, dll)
- Atomic Apply (rollback jika gagal)
- Remote Lease (koordinasi multi-device)
- Human QA (gerbang manual)
- Incident Handling (auto rollback + handoff)
- Bundle Export (pindah AI session)

## Quick Start

### Install

    curl -fsSL https://raw.githubusercontent.com/nafialwi/expert-xp-control/xp-engine/installer.sh | sh

### Mulai

    xp help

## Dokumentasi

- [Quick Start](docs/quickstart.md)
- [Workflow](docs/workflow.md)
- [Commands](docs/commands.md)
- [Concepts](docs/concepts.md)
- [Project Setup](docs/project-setup.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)

## Branch di Repo Ini

- main — control-repo state (lease management XP, jangan di-touch)
- xp-engine — source XP + dokumentasi + installer (branch publik untuk install)

## Lisensi

MIT
