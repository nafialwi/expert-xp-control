# Changelog

## 2.1.0 — 2026-09-13

- Promotes the tested XP+ RC line to stable after XP+-09 universal, Legacy, Next, clean-install, upgrade, installed-candidate rollback, schema/handshake, and A-RB gates.
- Product remains **XP+** with executable `xp`; `.xp/`, `XP_PKG_*`, registry identity, and profile/state/protocol v1 remain compatible.
- The user's real active XP is not changed by XP+-09.
## 2.1.0-rc1 — 2026-09-13

- Product display becomes **XP+** while the executable remains `xp`.
- RC install is side-by-side; the real active engine is not promoted at XP+-08.
- A+ acceptance uses **Zone 1** full-tree byte immutability for originals and
  **Zone 2** canonical-source protection for temporary copies.
- XP+-09 compatibility evidence must expose independent Zone 1 / Zone 2 proof
  columns.
- **Generic Toolchain Adapter** is user-approved as an **optional-only**
  capability; Smart Onboarding cannot auto-select it. The nine Qwen security
  guards remain mandatory regressions.
- Profile/state/package protocol remain version 1; `.xp/`, `XP_PKG_*`, registry
  identity, checkpoints, and work branches remain compatible.

<!-- XP+-10 RC18.3 BOOTSTRAP KNOWN LIMITATION -->
## XP+ 2.1.0 — rc18.3 one-time upgrade limitation

Recorded: `2026-09-13T06:55:10.142751+00:00`.

The rc18.3 built-in `xp upgrade` is defective: it writes `versions/` and
`active-version` outside the canonical `.expert-workstation` state root.
It can therefore print an upgrade-success message while canonical
`active-version` remains `2.0.0-rc18.3`.

The supported one-time path from rc18.3 to XP+ 2.1.0 is the published
`xp-rc183-to-210-bootstrap.py` release asset together with
`XP_PLUS_2.1.0_ENGINE.zip` and `SHA256SUMS.txt`. The bootstrap is stdlib-only
and delegates lifecycle validation/activation/health-check/rollback semantics
to XP+ `EngineLifecycle`; it does not implement a second activation path.

For origin >= 2.1.0, `xp upgrade` remains the supported EngineLifecycle public
update path.

Legacy `<home>/active-version` and `<home>/versions` outside the canonical XP
root are a **REPORT-ONLY** compatibility finding. XP and the bootstrap never
delete them automatically; cleanup requires explicit user approval.

<!-- XP+-10 A-HC HEALTH AUTHORITY RESTORATION -->
## XP+-10 A-HC — lifecycle health authority restoration

Recorded: `2026-09-13T06:55:10.143312+00:00`.

Stable 2.1.0 restores the locked `EngineLifecycle.health_check(version)`
interface. The method returns an audit-ready structured result (`ok` plus
per-check records) and reuses stable primitives for candidate/import integrity,
CLI startup, canonical schema readability, registry/state-v1 readability, and
a no-mutation `xp self-test`.

`activate_with_health_check(..., health_check=None)` keeps test injection
backward-compatible, but production `None` means `self.health_check(version)`.
`xp upgrade`, candidate promotion, and the rc18.3 bootstrap therefore share one
engine-owned health authority. Bootstrap code contains no health semantics.

HC5 also restores two additive locked-plan API surfaces found by the one-time
contract sweep: `EngineCandidate(...)` and `BundleBuilder.compact()/deep()`.
The full sweep is recorded in `docs/XP_PLUS_INTERFACE_CONTRACT_SWEEP.md`.

**Permanent XP+ rule (HC8):** every injectable dependency or callback on a
lifecycle-critical production path must have an engine-provided,
regression-tested production default. Injection is for tests; defaults are for
truth. This rule was established by the XP+-08 V3 candidate-match masking
incident and the XP+-10 missing health-authority incident.
