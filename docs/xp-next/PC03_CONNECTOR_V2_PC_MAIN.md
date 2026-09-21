# PC-03 — Connector V2 / PC Main

Status: implemented and accepted on the Windows + WSL2 workstation.

## Goal

Make the PC the primary execution device for GPT-driven project work.

Normal path:

GPT -> Supabase job router -> pc-main -> project workspace on WSL2.

The Android/Termux connector is no longer required for the three main projects.

## Workstation authority

Primary workspace root: /home/rahmawan/WORKSTATION/projects

Primary agent: pc-main

The agent accepts only jobs explicitly targeted to pc-main. Its local guard rejects initial working directories outside the workstation projects root. Deploy-class jobs remain locally blocked unless explicitly enabled.

Secrets are stored outside the repository in ~/.config/xp-agents/pc-main.env and must never be committed.

## Connector V2 database contract

The bridge was extended additively with target_agent_id, claimed_at, lease_expires_at, and claim_attempts.

RPC boundaries are xp_claim_job_v2, xp_renew_job_v2, xp_finish_job_v2, and xp_agent_heartbeat_v2.

Claiming is target-specific and uses a database-side atomic claim boundary. Legacy V1 RLS was narrowed so the old Termux runner can only see or update untargeted rows.

## PC acceptance

A targeted job was claimed and completed by pc-main on NAFI-ALWI-PC as user rahmawan.

XP Next:
- branch planning/xp-next-bootstrap
- starting HEAD 2f5e418719e47513f2fa5f18b692da266f71673c
- 92 tests PASS
- working tree clean

Segeran Jiwa Next:
- repository nafialwi/segeran-jiwa-pos-next
- branch work/cs06743-patch3-hardening
- accepted HEAD 0e543ab50b66c5dafafabb81d78a3171c76173e5
- Node v24.18.0
- npm 11.16.0
- JS tests 74 PASS
- Python tests 199 PASS
- production build PASS
- working tree clean

Segeran Jiwa Legacy:
- repository nafialwi/segeran-jiwa-qris-bridge-beta
- PC checkout segeran-jiwa-pos-legacy
- branch main
- accepted HEAD 4b32e91111fa2e78b34ff80ba0f432971b3c24fa

Legacy verification currently has one source-baseline failure in tests/legacy-cup-01b-product-cup-ui.test.mjs. The same targeted test fails on the Termux checkout at the same canonical source state, so it is not a PC migration regression.

## Local runtime

Node v24.18.0 and npm 11.16.0 are installed user-locally under ~/WORKSTATION/tools and exposed through ~/.local/bin.

## Safety

XP 2.1.0 stable source remains untouched. No production deployment was performed. No project database migration was performed as part of project checkout acceptance.
