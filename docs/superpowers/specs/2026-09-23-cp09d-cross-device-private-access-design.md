# CP-09D — Cross-device Private Access Design

Date: 2026-09-23  
Branch: `planning/xp-next-bootstrap`  
Baseline checkpoint: CP-09C Visual UX Convergence  
Baseline SHA: `f7cdbf8a69830954638c2deaf8b578e437f592ad`

## 1. Intent

CP-09D enables a trusted phone to use the same Expert XP instance that runs on the PC, without creating a second XP engine on the phone and without exposing the XP Visual Gateway directly to the LAN or public Internet.

The desired user experience is:

```text
Phone browser / installed PWA
        |
        | private encrypted transport
        v
Trusted PC
        |
        v
XP Visual Gateway
127.0.0.1:8765
        |
        v
WorkSessionService
        |
        v
XP Next engine / projects / Git / recovery
```

The phone is a client only. Project files, XP state, workers, verification, Apply/Discard, recovery, and Git remain on the PC.

## 2. Current verified baseline

CP-09C is remote-safe on `planning/xp-next-bootstrap`.

Current local services:
- XP Visual Gateway: `127.0.0.1:8765`
- local UAT reasoning fixture: `127.0.0.1:18081`

Current transport capability audit:
- Tailscale: not installed in WSL and not detected on Windows.
- Cloudflared: not installed.
- SSH client: available.
- SSH server: not installed.
- XP gateway: loopback-only.
- no public port forwarding is configured by this project.

The phone currently opening `127.0.0.1:8765` sees its own local service/PWA, not the PC service. CP-09D fixes the access path rather than duplicating the PC engine.

## 3. Chosen transport

Primary transport: **Tailscale private tailnet**, with the PC exposing the local XP PWA through Tailscale Serve or an equivalent private proxy.

Tailscale is preferred because:
- access is private to authenticated tailnet devices;
- encryption and device identity are provided by the transport;
- no router port forwarding is needed;
- XP can remain bound to loopback;
- the phone can use an HTTPS URL suitable for PWA/browser access;
- device removal/revocation can be performed outside XP.

Fallbacks are not automatic:
- Cloudflare Tunnel + Access may be evaluated only if Tailscale cannot satisfy the localhost/WSL routing requirement.
- SSH tunnel remains an engineering fallback, not the normal mobile UX.
- XP must never silently switch transports.

## 4. Non-negotiable network boundary

XP continues to bind only to loopback:

```text
127.0.0.1:8765
```

CP-09D must not change the XP gateway to:

```text
0.0.0.0:8765
```

and must not:
- add router/NAT port forwarding;
- listen directly on a LAN IP;
- expose XP to a public IP;
- disable Host/Origin/session protections to make remote access “work”;
- duplicate the XP state database on the phone.

The private transport terminates outside the XP engine boundary and proxies only to the local gateway.

## 5. Architecture

```text
┌──────────────────────────────┐
│ Trusted Android phone        │
│ Chrome / installed PWA       │
└──────────────┬───────────────┘
               │
               │ HTTPS / private tailnet
               ▼
┌──────────────────────────────┐
│ Tailscale transport          │
│ device identity + encryption │
└──────────────┬───────────────┘
               │
               │ private reverse proxy / Serve
               ▼
┌──────────────────────────────┐
│ PC transport endpoint        │
│ trusted-device access only   │
└──────────────┬───────────────┘
               │
               │ localhost proxy
               ▼
┌──────────────────────────────┐
│ XP Visual Gateway            │
│ 127.0.0.1:8765               │
│ Host/Origin/cookie guards    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ WorkSessionService           │
│ governed state transitions   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ XP Next engine               │
│ project / worker / verifier  │
│ Apply/Discard / recovery     │
└──────────────────────────────┘
```

## 6. Transport feasibility checkpoint

Before installing or changing XP behavior, CP-09D1 must prove how the transport reaches the WSL-hosted loopback service.

Preferred sequence:
1. install/connect Tailscale on Windows PC;
2. connect Tailscale on the trusted phone;
3. verify device identity/reachability;
4. determine whether Windows Tailscale Serve can proxy to the WSL-hosted `http://127.0.0.1:8765` through current localhost forwarding;
5. if yes, keep Tailscale on Windows only;
6. if no, evaluate a Tailscale endpoint inside WSL while preserving XP loopback binding;
7. do not fall back to public exposure.

The feasibility result must be documented before transport implementation is treated as complete.

## 7. Remote request trust model

The existing CP-09C gateway assumes same-origin loopback browser access. Remote private access introduces a different browser origin, so CP-09D must make that change explicit rather than weakening validation.

The gateway will distinguish two approved access profiles:

### LOCAL

```text
Origin/Host corresponds to local loopback URL
Transport = local
Device trust = current PC
```

### REMOTE_PRIVATE

```text
Origin/Host corresponds to explicitly configured private HTTPS origin
Transport = private tailnet
Device trust = authenticated transport + XP session
```

Unknown origins/hosts are rejected.

The allowed private origin must be explicit and bounded, for example:

```text
https://<pc-name>.<tailnet-name>.ts.net
```

The exact hostname is discovered at setup time and stored as configuration; it is never inferred from arbitrary request headers.

## 8. Browser/session security

Private transport identity is necessary but not sufficient. XP retains its own browser-session protections.

Required behavior:
- initial GET establishes an XP session cookie;
- mutation requests require a valid session cookie;
- mutation requests require an approved Origin;
- Host must match the configured access profile;
- no wildcard CORS;
- no credential reflection;
- no arbitrary proxy target selection;
- session cookies use secure attributes appropriate for HTTPS remote access;
- local HTTP access continues to work on loopback without weakening remote HTTPS handling.

Remote mode must not expose tokens, worker prompts, verifier argv, credentials, hidden reasoning, local filesystem internals, or unrestricted environment data.

## 9. Access-mode awareness in the PWA

The PWA must visibly show whether the user is local or connected remotely.

Example:

```text
LOCAL / AMAN
Gateway hanya tersedia pada perangkat ini.
```

or:

```text
REMOTE PRIVATE / AMAN
Terhubung ke XP PC melalui perangkat terpercaya.
```

The indicator is informational; it does not change the safety rules for worker approval, sandbox approval, review, Apply/Discard, or recovery.

The PWA must never label a remote session as “LOCAL”.

## 10. Phone UX requirements

The mobile UI must preserve the same information architecture introduced in CP-09C:
- Home
- Work
- Projects
- Activity
- Settings

On a phone:
- sidebar may collapse into a drawer/bottom navigation;
- primary action buttons must remain comfortably tappable;
- review diff must remain readable without horizontal chaos;
- Apply and Discard must remain visually distinct;
- status/approval cards may stack vertically;
- technical details should stay secondary;
- browser refresh must restore the current work session from XP durable state.

The phone must not show a separate legacy XP visual workstation once the user is using the PC-backed private URL.

## 11. Remote work-session behavior

Remote access does not create a separate job model.

A work session created from the phone is the same durable XP Next work session that would be visible from the PC:
- same job id;
- same revision;
- same worker recommendation;
- same sandbox;
- same verifier result;
- same review fingerprint;
- same Apply/Discard decision;
- same recovery point;
- same Activity Trail.

If PC and phone have the same session open simultaneously, stale revision protection remains authoritative. The second device must refresh if another device has already changed the session.

## 12. Disconnect and reconnect semantics

Loss of phone connectivity must not cancel or repeat a mutating operation.

Required behavior:
- browser disconnect does not reset the server-side session;
- reconnect/refresh fetches the latest durable state;
- GET may be retried safely;
- stale POST is rejected by existing optimistic revision protection;
- Apply/Discard must never repeat automatically after reconnect;
- worker execution is never restarted just because the phone reconnects;
- a job that is already `READY_TO_REVIEW` remains reviewable after reconnect.

If the PC itself sleeps or XP stops, the phone should show an unavailable/reconnect state rather than silently switching to a local phone XP instance.

## 13. Trusted-device lifecycle

The transport trust lifecycle remains explicit:
- connect the intended phone to the private tailnet;
- do not authorize unknown devices;
- remove/revoke a lost phone from the tailnet;
- XP sessions remain separate from tailnet membership;
- remote access can be disabled without changing XP project/state data.

CP-09D does not build a new device-management platform inside XP. It consumes the transport's authenticated device boundary and keeps XP's own session guard.

## 14. Failure behavior

Examples:

- Tailscale unavailable on phone → show transport unavailable; do not fall back to phone-local XP.
- PC offline/asleep → remote URL unavailable; no XP state is altered.
- invalid remote Host → HTTP 403.
- invalid remote Origin → HTTP 403.
- missing XP session cookie → HTTP 403 for mutation.
- non-HTTPS remote origin → rejected for REMOTE_PRIVATE.
- unconfigured remote hostname → rejected.
- stale revision from second device → HTTP 409 and UI refresh prompt.
- worker/verifier failure → existing XP `NEEDS_ATTENTION` behavior.
- transport disconnect during worker execution → worker may continue on PC; reconnect reads durable state.
- transport disconnect before Apply/Discard response → client must re-fetch state before any retry.

## 15. Testing strategy

CP-09D is TDD-first for XP code changes.

Test layers:

1. access-profile unit tests:
   - LOCAL loopback accepted;
   - configured REMOTE_PRIVATE HTTPS host/origin accepted;
   - arbitrary host/origin rejected;
   - HTTP remote origin rejected.

2. gateway mutation tests:
   - cookie + approved remote Origin required;
   - wildcard CORS absent;
   - stale revision still returns 409.

3. UI tests:
   - LOCAL and REMOTE_PRIVATE badges render correctly;
   - phone-sized layout keeps navigation/actions usable;
   - reconnect state does not invent local fallback.

4. fixture E2E:
   - phone-like remote-origin request can create/load a session through the private profile;
   - reach `READY_TO_REVIEW`;
   - original project remains unchanged before Apply;
   - remote Discard path;
   - remote Apply path;
   - reconnect at `READY_TO_REVIEW`;
   - stale second-client decision rejected.

5. manual transport UAT:
   - actual phone opens the private PC-backed PWA;
   - phone and PC show the same work session;
   - no legacy phone-local XP confusion;
   - remote review Apply/Discard on isolated fixture only.

Existing CP-09B, CP-09C, AF-10, and full XP Next regressions must remain green.

## 16. UAT fixture boundary

Human remote UAT uses an isolated fixture project under the XP UAT area, never Segeran Jiwa production.

Before review:
- source must be clean;
- baseline content must be known;
- sandbox verifier must PASS;
- original source must remain unchanged.

UAT may test both:
- Discard from phone;
- Apply from phone.

A fresh fixture is used for each destructive decision so expected state is obvious.

## 17. Installation and system-change boundary

Installing Tailscale or connecting a device is an external system/account action and requires the user's explicit participation where the installer/login flow requires it.

CP-09D may automate:
- package/download preparation where supported;
- configuration files;
- XP gateway configuration;
- tests;
- service status checks.

It must not claim that Tailscale is connected until actual device/account state proves it.

No Cloudflare/Tailscale account secrets are stored in the XP repository.

## 18. Portability boundary

CP-09D proves trusted phone access to the current PC-hosted XP instance.

It does not yet prove:
- full XP installation on a new PC;
- disaster recovery onto a replacement PC;
- standalone XP engine on Android;
- final `xp-next -> xp` release cutover.

Those remain later portability/recovery/final-release phases.

## 19. Acceptance criteria

CP-09D is accepted only when all of the following are proven:

```text
PC XP GATEWAY          : remains loopback-only
PRIVATE TRANSPORT      : connected and authenticated
PHONE -> PC PWA        : PASS
HTTPS PRIVATE ORIGIN   : PASS
LOCAL ACCESS           : PASS
REMOTE PRIVATE ACCESS  : PASS
UNKNOWN HOST/ORIGIN    : BLOCKED
SESSION COOKIE GUARD   : PASS
STALE REVISION GUARD   : PASS
REMOTE READY_TO_REVIEW : PASS
REMOTE DISCARD FIXTURE : PASS
REMOTE APPLY FIXTURE   : PASS
RECONNECT/REFRESH      : PASS
PC/PHONE SAME SESSION  : PASS
LEGACY LOCAL FALLBACK  : NONE
XP NEXT REGRESSION     : PASS
CP09B/CP09C REGRESSION : PASS
AF-10 VISUAL           : PASS
WORKTREE               : CLEAN
SEG. JIWA              : UNTOUCHED
PRODUCTION DB          : UNTOUCHED
PUBLIC PORT EXPOSURE   : NONE
```

## 20. Follow-up

After CP-09D:
- refine any phone-specific UX issues found during UAT;
- validate broader portability/recovery to another PC;
- validate launcher/startup behavior;
- perform final `xp-next -> xp` cutover only after desktop and remote-phone paths are both stable.
