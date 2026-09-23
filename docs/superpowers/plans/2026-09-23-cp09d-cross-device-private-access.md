# CP-09D Cross-device Private Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a trusted Android phone use the same PC-hosted Expert XP PWA over a private authenticated Tailscale path while the XP Visual Gateway remains bound to loopback and preserves all CP-09B/CP-09C safety controls.

**Architecture:** Keep XP on `127.0.0.1:8765`. Tailscale Serve terminates private HTTPS outside XP and reverse-proxies to the loopback gateway. XP learns one explicit `REMOTE_PRIVATE` origin, validates Host/Origin/session plus Tailscale identity headers for remote requests, and exposes access mode to the PWA without creating a second engine or state store on the phone.

**Tech Stack:** Python 3.11+, stdlib `http.server`, `dataclasses`, `urllib.parse`, existing XP Next gateway/session services, JavaScript/CSS PWA, stdlib `unittest`, Windows Tailscale client/Serve, Android Tailscale client.

**Spec:** `docs/superpowers/specs/2026-09-23-cp09d-cross-device-private-access-design.md`

## Global Constraints

- XP Visual Gateway stays bound to `127.0.0.1` / loopback only.
- Do not bind XP to `0.0.0.0`, a LAN IP, or a public interface.
- Do not configure router/NAT port forwarding.
- Tailscale Serve is the primary transport; Tailscale Funnel is prohibited for XP because Funnel is public.
- No silent fallback to Cloudflare, SSH, LAN exposure, or phone-local XP.
- The phone is a browser/PWA client only; XP engine, project files, state DB, Git, workers, verifier, Apply/Discard, and recovery remain on the PC.
- REMOTE_PRIVATE accepts only one explicitly configured HTTPS origin during CP-09D.
- Remote requests must not weaken Host, Origin, session-cookie, revision, fingerprint, source-HEAD, verifier, or approval guards.
- Tailscale/account secrets are never stored in the repository.
- Installing/signing in to Tailscale is an external system/account action; execution must stop for explicit user participation when installer/login/device authorization is required.
- Segeran Jiwa production is excluded from CP-09D testing and UAT.
- Existing CP-09B, CP-09C, AF-10, and full XP Next regressions remain green.

## Current external assumptions to prove, not merely assume

Current Tailscale Serve documentation states that Serve can privately reverse-proxy a local HTTP service, terminates HTTPS for the tailnet URL, and adds `Tailscale-User-Login`, `Tailscale-User-Name`, and `Tailscale-User-Profile-Pic` identity headers for ordinary tailnet user traffic. The docs also recommend keeping identity-header backends on localhost. CP-09D uses those properties only after Task 1 proves them on this PC/phone path.

The exact Host header seen by the WSL backend is deliberately not assumed. Task 1 records it before gateway remote-profile code is enabled.

## File Structure

- Create: `next/src/xp_next/visual_access.py` — LOCAL/REMOTE_PRIVATE access-policy parsing and request classification.
- Modify: `next/src/xp_next/visual_gateway.py` — access-policy enforcement, secure cookie behavior, remote access projection.
- Modify: `next/src/xp_next/cli.py` — explicit `--remote-private-origin` gateway option; bind host remains loopback.
- Modify: `web/xp_visual/app.js` — access-mode badge, remote-unavailable/reconnect behavior, stale-session refresh messaging.
- Modify: `web/xp_visual/styles.css` — mobile access badge/reconnect state and responsive review/action refinements.
- Create: `next/tests/test_cp09d_access_policy.py`.
- Create: `next/tests/test_cp09d_visual_gateway_remote.py`.
- Create: `next/tests/test_cp09d_mobile_ui.py`.
- Create: `next/tests/test_cp09d_remote_e2e.py`.
- Create: `scripts/cp09d_remote_probe.py` — read-only remote URL/status probe; no credentials persisted.
- Create: `docs/xp-next/CP09D_CROSS_DEVICE_PRIVATE_ACCESS.md` — feasibility, tests, UAT, transport evidence, rollback.

## Review Focus

1. Reverse proxy changes `Host` unexpectedly: remote access must fail closed until the actual Host is explicitly captured and configured.
2. A tailnet-shared/unknown user reaches Serve: missing or unexpected Tailscale identity must be rejected by XP remote mode.
3. PC and phone submit the same revision: first valid mutation wins; the stale device receives 409 and refreshes.
4. Phone loses connectivity after sending Apply/Discard but before receiving the response: client re-fetches durable state before offering any retry.
5. Remote configuration is present but Tailscale/PC is unavailable: PWA must show remote unavailable, never silently open or switch to phone-local XP.

---

### Task 1: Prove the Windows/WSL Tailscale Serve Transport Path

**Files:**
- Create: `scripts/cp09d_remote_probe.py`
- Create/update: `docs/xp-next/CP09D_CROSS_DEVICE_PRIVATE_ACCESS.md`

**Interfaces:**
- Consumes: current loopback-only XP gateway and Windows/Android Tailscale clients.
- Produces: captured private HTTPS origin, observed backend Host header, observed Tailscale identity headers, and a documented transport verdict: `WINDOWS_SERVE_TO_WSL_LOOPBACK=PASS|BLOCKED`.

This task changes no XP source behavior.

- [ ] **Step 1: Record the pre-install/pre-connect boundary**

Run on the PC and record:
```text
XP listener        = 127.0.0.1:8765 only
Windows Tailscale  = absent or current version/status
WSL Tailscale      = absent or current version/status
Public listener    = none for 8765
```

Use `ss -ltnp`, Windows service/CLI discovery, and `git status`. Fail if XP already listens on a non-loopback address.

- [ ] **Step 2: Stop for explicit user participation before Tailscale installation/login**

Do not install, log in, authorize, or connect an account silently. Ask the user to approve the installation/login step and complete any browser/device authorization that Tailscale requires.

After the user approves installation, prefer this deterministic Windows path when WinGet is available:
```powershell
winget list --id Tailscale.Tailscale
winget install --id Tailscale.Tailscale --exact --source winget --accept-package-agreements --accept-source-agreements
```
If WinGet is unavailable or the package install fails, stop and use the official signed Windows installer interactively; do not download from an unverified mirror. The user completes the Tailscale login/browser authorization and installs/signs in to the Android Tailscale app.

After participation, record:
```text
PC device connected      : YES/NO
Phone device connected   : YES/NO
Same intended tailnet    : YES/NO
MagicDNS/HTTPS available : YES/NO
```

If any required item is NO, stop CP-09D transport work without changing XP.

- [ ] **Step 3: Prove Windows can reach the WSL loopback service**

From Windows, request the WSL-hosted XP loopback URL:
```powershell
curl.exe -I http://127.0.0.1:8765/
```

Expected: the request reaches the XP service. A 200 is ideal; a deliberate XP Host-policy 403 still proves TCP/HTTP reachability if the backend log confirms the request. If Windows cannot reach WSL localhost, do not weaken XP; evaluate Tailscale-in-WSL as the documented fallback architecture.

- [ ] **Step 4: Run a temporary header-capture backend on WSL loopback**

Use a temporary UAT-only Python HTTP server under `~/XP_UAT/cp09d-transport/`, bound to `127.0.0.1:18765`. The helper is not product code and does not enter the repository:

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({
            "host": self.headers.get("Host"),
            "tailscale_user_login_present": bool(
                self.headers.get("Tailscale-User-Login")
            ),
            "tailscale_user_name_present": bool(
                self.headers.get("Tailscale-User-Name")
            ),
            "tailscale_profile_pic_present": bool(
                self.headers.get("Tailscale-User-Profile-Pic")
            ),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

ThreadingHTTPServer(("127.0.0.1", 18765), Handler).serve_forever()
```

Do not echo the actual login/name/profile values into the report; record presence only and separately capture the backend Host.

- [ ] **Step 5: Configure Tailscale Serve to the temporary loopback backend**

Configure the temporary endpoint with:
```powershell
tailscale serve --bg http://127.0.0.1:18765
```
Confirm it with `tailscale serve status`. Use Serve, never Funnel.

Record:
- exact private HTTPS URL;
- Serve status/config;
- whether the phone can open it;
- backend-observed `Host`;
- backend-observed `Tailscale-User-Login`;
- whether the connection is tailnet-private.

- [ ] **Step 6: Prove no public exposure**

From Serve status/config and listener audit, verify:
- no Funnel endpoint;
- no router/public listener created by XP;
- XP remains `127.0.0.1:8765`;
- temporary probe remains `127.0.0.1:18765`.

- [ ] **Step 7: Write the read-only repository probe**

`scripts/cp09d_remote_probe.py` accepts `--url` and performs GET only:

```python
def probe(url: str, *, timeout: float = 5.0) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("remote probe requires an https URL")
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {
            "status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "final_url": response.geturl(),
        }
```

No cookies, auth tokens, or account credentials are written to disk.

- [ ] **Step 8: Document the feasibility verdict and commit**

The report records the private origin/hostname and header shape but redacts personal login values. Commit only the probe and report. Do not commit Tailscale auth/account material.

---

### Task 2: Access Policy Model for LOCAL and REMOTE_PRIVATE

**Files:**
- Create: `next/src/xp_next/visual_access.py`
- Create: `next/tests/test_cp09d_access_policy.py`

**Interfaces:**
- Produces:
  - `AccessMode(str, Enum)` with `LOCAL`, `REMOTE_PRIVATE`
  - `AccessDecision`
  - `VisualAccessPolicy(local_origin: str, remote_private_origin: str | None, remote_proxy_host: str | None = None)`
  - `VisualAccessPolicy.classify(host_header: str, origin_header: str | None, tailscale_user_login: str | None, *, mutation: bool) -> AccessDecision`

- [ ] **Step 1: Write RED tests for remote-origin validation**

```python
def test_remote_origin_must_be_https_and_origin_only():
    with self.assertRaises(ValueError):
        VisualAccessPolicy(
            local_origin="http://127.0.0.1:8765",
            remote_private_origin="http://pc.tail.ts.net",
        )
    with self.assertRaises(ValueError):
        VisualAccessPolicy(
            local_origin="http://127.0.0.1:8765",
            remote_private_origin="https://pc.tail.ts.net/path",
        )
```

- [ ] **Step 2: Write RED classification tests**

Pin:
- local Host + local Origin mutation → LOCAL allowed;
- local GET without Origin → LOCAL allowed;
- exact configured remote Host + exact HTTPS Origin + non-empty `Tailscale-User-Login` → REMOTE_PRIVATE allowed;
- remote GET with exact Host + identity header → REMOTE_PRIVATE allowed;
- arbitrary Host → denied;
- remote HTTP Origin → denied;
- remote host with missing identity header → denied;
- remote Origin mismatch → denied.

- [ ] **Step 3: Verify RED**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest next.tests.test_cp09d_access_policy -v
```

Expected: import/module failure.

- [ ] **Step 4: Implement strict normalized origins**

Core shape:
```python
class AccessMode(str, Enum):
    LOCAL = "LOCAL"
    REMOTE_PRIVATE = "REMOTE_PRIVATE"

@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    mode: AccessMode | None
    secure_cookie: bool
    error: str | None = None

def _normalize_remote_origin(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("REMOTE_PRIVATE origin must be an https origin")
    origin = f"https://{parsed.netloc}"
    return origin, parsed.netloc
```

Local origins remain limited to loopback HTTP. Do not accept wildcard hosts, suffix matching, or arbitrary `.ts.net` values.

- [ ] **Step 5: Implement exact remote identity requirement**

REMOTE_PRIVATE is allowed only when `Tailscale-User-Login` is present and non-blank and the request Host matches `remote_proxy_host`. `remote_proxy_host` is the exact backend Host observed in Task 1; when omitted it defaults to the configured HTTPS origin netloc. This keeps the implementation correct whether Tailscale Serve preserves the public tailnet Host or rewrites it while proxying to localhost. The login value is never returned to the browser.

- [ ] **Step 6: Run Task 2 tests and full XP Next regression**

- [ ] **Step 7: Commit**

```bash
git add next/src/xp_next/visual_access.py   next/tests/test_cp09d_access_policy.py
git commit -m "CP09D access policy"
```
### Task 3: Enforce REMOTE_PRIVATE in the Visual Gateway Without Weakening Loopback

**Files:**
- Modify: `next/src/xp_next/visual_gateway.py`
- Modify: `next/src/xp_next/cli.py`
- Create: `next/tests/test_cp09d_visual_gateway_remote.py`

**Interfaces:**
- Consumes: `VisualAccessPolicy`.
- Changes:
  - `make_visual_gateway(..., remote_private_origin: str | None = None, remote_proxy_host: str | None = None)`
  - development CLI: `xp-next visual-gateway --remote-private-origin https://<exact-host> --remote-proxy-host <observed-backend-host>`
- Produces request-scoped access metadata:
  - `{"mode": "LOCAL", ...}`
  - `{"mode": "REMOTE_PRIVATE", ...}`

- [ ] **Step 1: Write RED GET and mutation tests**

Build the gateway with:
```python
server = make_visual_gateway(
    host="127.0.0.1",
    port=0,
    service=fake_service,
    static_root=static_root,
    remote_private_origin="https://xp-pc.example.ts.net",
    remote_proxy_host="xp-pc.example.ts.net",
)
```

Assert:
- local GET with `Host: 127.0.0.1:<port>` remains 200;
- remote GET with `Host: xp-pc.example.ts.net` and `Tailscale-User-Login` is 200;
- remote GET without identity is 403;
- unknown host is 403;
- remote mutation requires exact `Origin: https://xp-pc.example.ts.net`, session cookie, identity header, and JSON;
- local mutation continues to use the existing local origin;
- no `Access-Control-Allow-Origin: *` appears.

- [ ] **Step 2: Write RED cookie tests**

For local root:
```text
Set-Cookie: xp_session=...; HttpOnly; SameSite=Strict; Path=/
```

For REMOTE_PRIVATE root:
```text
Set-Cookie: xp_session=...; HttpOnly; SameSite=Strict; Secure; Path=/
```

The same server-side nonce may back both access paths in CP-09D, but the browser cookie attributes depend on the request access mode.

- [ ] **Step 3: Verify RED**

Expected: remote request tests fail because current gateway only accepts loopback Host/Origin.

- [ ] **Step 4: Inject access policy into the server**

Extend `XPVisualGateway.__init__`:

```python
self.access_policy = VisualAccessPolicy(
    local_origin=self.origin,
    remote_private_origin=remote_private_origin,
    remote_proxy_host=remote_proxy_host,
)
```

Because `self.origin` depends on the allocated port when `port=0`, construct the policy after `ThreadingHTTPServer` initializes and `server_address` is final.

- [ ] **Step 5: Replace loopback-only request checks with request classification**

Add:
```python
def _access_decision(self, *, mutation: bool) -> AccessDecision:
    return self.server.access_policy.classify(
        self.headers.get("Host", ""),
        self.headers.get("Origin"),
        self.headers.get("Tailscale-User-Login"),
        mutation=mutation,
    )
```

GET/static/API requests must classify successfully. POST calls the same classifier before checking the XP session cookie/content type.

Do not remove existing session-cookie or JSON checks.

- [ ] **Step 6: Emit request-scoped access mode in snapshot**

For `GET /api/v2/snapshot`, start from `service.visual_snapshot()` and add:

```python
snapshot["access"] = {
    "mode": decision.mode.value,
    "label": (
        "LOCAL / AMAN"
        if decision.mode is AccessMode.LOCAL
        else "REMOTE PRIVATE / AMAN"
    ),
    "detail": (
        "Gateway hanya tersedia pada perangkat ini."
        if decision.mode is AccessMode.LOCAL
        else "Terhubung ke XP PC melalui perangkat terpercaya."
    ),
}
```

Do not expose Tailscale login/name/profile headers.

- [ ] **Step 7: Add the explicit CLI option**

```python
visual_gateway.add_argument(
    "--remote-private-origin",
    default=None,
    help="exact private HTTPS origin accepted through the trusted proxy",
)
visual_gateway.add_argument(
    "--remote-proxy-host",
    default=None,
    help="exact Host header observed from the trusted local reverse proxy",
)
```

Pass it to `make_visual_gateway()`. The bind host default and validation remain `127.0.0.1`/loopback only.

- [ ] **Step 8: Run Task 3, CP-09B gateway, and full XP Next tests**

Expected: all pass; local behavior remains backward compatible.

- [ ] **Step 9: Commit**

```bash
git add next/src/xp_next/visual_gateway.py next/src/xp_next/cli.py   next/tests/test_cp09d_visual_gateway_remote.py
git commit -m "CP09D remote private gateway"
```

### Task 4: Mobile Access Mode, Reconnect, and No-local-fallback UX

**Files:**
- Modify: `web/xp_visual/app.js`
- Modify: `web/xp_visual/styles.css`
- Create: `next/tests/test_cp09d_mobile_ui.py`

**Interfaces:**
- Consumes: snapshot `access.mode/label/detail`.
- Produces:
  - visible `LOCAL / AMAN` or `REMOTE PRIVATE / AMAN` badge;
  - explicit unavailable/reconnect state;
  - stale 409 refresh guidance;
  - no automatic redirect/fallback to phone localhost.

- [ ] **Step 1: Write RED source-contract tests**

Pin static contracts in the PWA source:
```python
self.assertIn("REMOTE PRIVATE / AMAN", app_js)
self.assertIn("PC tidak tersedia", app_js)
self.assertIn("Muat ulang status", app_js)
self.assertNotIn("window.location = 'http://127.0.0.1:8765'", app_js)
```

Also assert CSS includes a mobile breakpoint and minimum primary-action tap height:
```python
self.assertRegex(styles, r"@media\s*\(max-width:\s*760px\)")
self.assertIn("min-height: 44px", styles)
```

- [ ] **Step 2: Verify RED**

Expected: access-mode/reconnect strings or styles are missing.

- [ ] **Step 3: Render the access badge from snapshot**

Add a small helper:
```javascript
function renderAccess(snapshot) {
  const access = snapshot?.access || {};
  const remote = access.mode === "REMOTE_PRIVATE";
  return {
    label: access.label || (remote ? "REMOTE PRIVATE / AMAN" : "LOCAL / AMAN"),
    detail: access.detail || "",
    remote,
  };
}
```

Use it in Home/Work shell status. Do not infer remote mode from `window.location.hostname`; server classification is authoritative.

- [ ] **Step 4: Add bounded reconnect state**

On fetch/network failure:
- preserve the last rendered non-mutating content;
- show `PC tidak tersedia`;
- provide `Muat ulang status`;
- do not auto-submit/repeat the previous POST;
- do not navigate to `127.0.0.1`.

For HTTP 409:
- show `Status berubah di perangkat lain. Muat ulang status sebelum melanjutkan.`;
- disable stale decision controls until refreshed.

- [ ] **Step 5: Refine phone layout**

At <=760 px:
- primary nav becomes compact/stacked existing mobile pattern;
- Work cards are single-column;
- diff preview wraps/scrolls inside its card without expanding page width;
- Apply/Discard remain separate full-width or paired tappable actions;
- all primary action buttons use `min-height: 44px`;
- access badge remains visible near the top.

- [ ] **Step 6: Run Node syntax and CP-09C/CP-09D UI tests**

```bash
node --check web/xp_visual/app.js
node --check web/xp_visual/sw.js
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest   next.tests.test_cp09c_visual_ui   next.tests.test_cp09d_mobile_ui -v
```

- [ ] **Step 7: Commit**

```bash
git add web/xp_visual/app.js web/xp_visual/styles.css   next/tests/test_cp09d_mobile_ui.py
git commit -m "CP09D mobile remote UX"
```
### Task 5: Simulated REMOTE_PRIVATE End-to-End Safety

**Files:**
- Create: `next/tests/test_cp09d_remote_e2e.py`

**Interfaces:**
- Consumes: real Visual Gateway + WorkSessionService fixture from CP-09B.
- Produces: remote-origin proof without requiring the real Tailscale network in automated tests.

- [ ] **Step 1: Build a remote HTTP test client**

The client sends:
```text
Host: xp-pc.example.ts.net
Origin: https://xp-pc.example.ts.net
Tailscale-User-Login: uat-user@example.invalid
Cookie: xp_session=<cookie obtained from remote root GET>
Content-Type: application/json
```

The email is a fixture value only.

- [ ] **Step 2: Write RED remote session parity test**

Open the same job through local and remote clients and assert:
```python
self.assertEqual(local["id"], remote["id"])
self.assertEqual(local["revision"], remote["revision"])
self.assertEqual(local["state"], remote["state"])
self.assertEqual(
    local["review"]["change_fingerprint"],
    remote["review"]["change_fingerprint"],
)
```

- [ ] **Step 3: Write RED remote Discard E2E**

Remote client:
create → confirm worker → approve sandbox → execute → `READY_TO_REVIEW` → Discard.

Assert original fixture remains `SAFE\n`, final state `CANCELLED`, status `DISCARDED`, and local client sees the same final state.

- [ ] **Step 4: Write RED remote Apply E2E**

Fresh fixture:
create → approvals → execute → review → Apply.

Assert final state `COMPLETED`, original is `CHANGED\n`, recovery exists, post-Apply verifier passes, and local client sees the same final state.

- [ ] **Step 5: Write RED reconnect/stale-second-device test**

At `READY_TO_REVIEW`:
1. local and remote clients read revision N;
2. one client Discards or Applies;
3. second client sends its stale revision N;
4. assert HTTP 409;
5. second client GETs latest state;
6. assert no duplicate worker/Apply/Discard side effect.

- [ ] **Step 6: Write RED unknown identity/origin tests**

Assert 403 for:
- missing `Tailscale-User-Login`;
- wrong Host;
- wrong HTTPS Origin;
- HTTP remote Origin;
- valid remote Host/Origin but invalid XP session cookie.

- [ ] **Step 7: Run dedicated CP-09D and full XP Next regression**

Record fresh exact totals; do not assume the prior 208 count.

- [ ] **Step 8: Commit**

```bash
git add next/tests/test_cp09d_remote_e2e.py
git commit -m "CP09D remote private E2E"
```

### Task 6: Configure Real Tailscale Serve to XP and Run Phone UAT

**Files:**
- Update: `docs/xp-next/CP09D_CROSS_DEVICE_PRIVATE_ACCESS.md`

**Interfaces:**
- Consumes: exact private HTTPS origin proven in Task 1 and gateway remote-profile support from Tasks 2-5.
- Produces: actual phone→PC evidence.

This task contains external system/account changes. Stop for user participation where Tailscale installer, account login, device approval, or Android app interaction requires it.

- [ ] **Step 1: Start the CP-09D gateway with the exact private origin**

Example shape only; use the actual captured origin:
```bash
xp-next visual-gateway \
  --host 127.0.0.1 \
  --port 8765 \
  --remote-private-origin "https://xp-pc.<actual-tailnet>.ts.net" \
  --remote-proxy-host "<exact-host-observed-in-task-1>"
```

Verify with `ss -ltnp` that XP still listens only on `127.0.0.1:8765`.

- [ ] **Step 2: Point Tailscale Serve to XP loopback**

Configure the XP endpoint with:
```powershell
tailscale serve --bg http://127.0.0.1:8765
```
Then verify it with `tailscale serve status`. If the installed client reports a syntax incompatibility, stop and update the documented command from that client's `tailscale serve --help`; do not improvise Funnel or a public listener.

Verify:
- Serve URL equals the configured XP remote origin;
- Serve is private, not Funnel;
- no public listener is introduced.

- [ ] **Step 3: Open the private HTTPS URL on the phone**

Expected:
- new CP-09C/09D PWA, not the phone-local legacy UI;
- badge shows `REMOTE PRIVATE / AMAN`;
- active project/session matches PC;
- Home/Work/Projects/Activity/Settings are usable at phone width.

- [ ] **Step 4: Human UAT — remote Discard fixture**

Create a fresh isolated fixture job and take it to `READY_TO_REVIEW`. Before decision prove:
```text
verifier = PASS
original = SAFE
git status = CLEAN
allowed = APPLY, DISCARD
```

User taps `Buang Hasil` from phone. Verify on PC:
```text
final state = CANCELLED
apply status = DISCARDED
original = SAFE
worker did not rerun
```

- [ ] **Step 5: Human UAT — remote Apply fixture**

Use a fresh fixture. User taps `Terapkan` from phone. Verify:
```text
final state = COMPLETED
apply status = APPLIED
original = CHANGED
post verifier = PASS
recovery ref = present
```

- [ ] **Step 6: Human UAT — reconnect**

At a fresh `READY_TO_REVIEW` fixture:
- disconnect phone Tailscale/network or close browser;
- reconnect/reopen the private URL;
- verify same job/revision/review fingerprint;
- verify worker has not rerun;
- verify no Apply/Discard occurred automatically.

- [ ] **Step 7: Human UAT — simultaneous PC/phone stale revision**

Open same review on PC and phone. Make one decision on one device. Attempt the stale action from the other device only on a disposable fixture. Expected: stale action blocked/refresh required; no duplicate mutation.

- [ ] **Step 8: Verify no local fallback confusion**

While testing the private URL, if transport is unavailable the phone must show unavailable/reconnect behavior. It must not silently switch to the legacy `127.0.0.1:8765` service on the phone.

- [ ] **Step 9: Record transport/device evidence without personal secrets**

Report only:
- PC Tailscale connected: YES/NO;
- phone connected: YES/NO;
- private HTTPS host (hostname is acceptable);
- identity header present: YES/NO;
- login value redacted;
- Serve private: YES/NO;
- Funnel/public exposure: NONE.

---

### Task 7: Final Verification, Rollback Instructions, Safe Checkpoint

**Files:**
- Finalize: `docs/xp-next/CP09D_CROSS_DEVICE_PRIVATE_ACCESS.md`

**Interfaces:**
- Produces: CP-09D safe checkpoint and explicit transport disable/rollback procedure.

- [ ] **Step 1: Run dedicated CP-09D tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest   next.tests.test_cp09d_access_policy   next.tests.test_cp09d_visual_gateway_remote   next.tests.test_cp09d_mobile_ui   next.tests.test_cp09d_remote_e2e -v
```

- [ ] **Step 2: Run CP-09B and CP-09C regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest   next.tests.test_cp09b_session_store   next.tests.test_cp09b_execution_phases   next.tests.test_cp09b_work_session_service   next.tests.test_cp09b_visual_gateway   next.tests.test_cp09b_e2e   next.tests.test_cp09c_visual_ui -q
```

- [ ] **Step 3: Run full XP Next regression and record exact fresh count**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/next/src" python3 -m unittest discover -s next/tests -q
```

- [ ] **Step 4: Run AF-10/PWA/syntax gates**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 -m unittest tests.test_af10_visual_workstation -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" python3 scripts/xp_visual.py --self-test
node --check web/xp_visual/app.js
node --check web/xp_visual/sw.js
python3 -m py_compile   next/src/xp_next/visual_access.py   next/src/xp_next/visual_gateway.py   next/src/xp_next/cli.py
git diff --check
```

- [ ] **Step 5: Re-audit listeners and Serve mode**

Evidence must show:
```text
XP gateway      = 127.0.0.1:8765
XP LAN listener = NONE
Tailscale Serve = PRIVATE
Tailscale Funnel= NONE
router forward  = NONE created by this work
```

- [ ] **Step 6: Document rollback**

Document and verify this rollback sequence:
```powershell
tailscale serve --https=443 off
tailscale serve status
```
If the endpoint was created under a non-default HTTPS port, use that exact port instead of 443. Then restart XP without `--remote-private-origin` / `--remote-proxy-host`, confirm `127.0.0.1:8765` local access, and leave project/state DB untouched. Do not use `tailscale serve reset` unless CP-09D is the only Serve configuration, because reset would remove unrelated Serve endpoints.

Rollback must not delete XP work sessions or recovery points.

- [ ] **Step 7: Final checkpoint report**

Record all acceptance evidence:
```text
CP-09D SAFE CHECKPOINT
PC XP GATEWAY          : LOOPBACK ONLY
PRIVATE TRANSPORT      : CONNECTED / AUTHENTICATED
PHONE -> PC PWA        : PASS
HTTPS PRIVATE ORIGIN   : PASS
LOCAL ACCESS           : PASS
REMOTE PRIVATE ACCESS  : PASS
TAILSCALE IDENTITY     : PASS (VALUE REDACTED)
UNKNOWN HOST/ORIGIN    : BLOCKED
SESSION COOKIE GUARD   : PASS
STALE REVISION GUARD   : PASS
REMOTE READY_TO_REVIEW : PASS
REMOTE DISCARD FIXTURE : PASS
REMOTE APPLY FIXTURE   : PASS
RECONNECT/REFRESH      : PASS
PC/PHONE SAME SESSION  : PASS
LEGACY LOCAL FALLBACK  : NONE
XP NEXT REGRESSION     : PASS (FRESH COUNT)
CP09B/CP09C REGRESSION : PASS
AF-10 VISUAL           : PASS
WORKTREE               : CLEAN
SEG. JIWA              : UNTOUCHED
PRODUCTION DB          : UNTOUCHED
PUBLIC PORT EXPOSURE   : NONE
```

- [ ] **Step 8: Commit, push, and remote-verify**

```bash
git add next/src/xp_next next/tests web/xp_visual   scripts/cp09d_remote_probe.py   docs/xp-next/CP09D_CROSS_DEVICE_PRIVATE_ACCESS.md
git commit -m "CP09D cross-device private access"
git push origin planning/xp-next-bootstrap
git fetch origin --prune
test "$(git rev-parse HEAD)" =      "$(git rev-parse origin/planning/xp-next-bootstrap)"
git status --short --branch
```

## Final Acceptance Gate

Do not claim CP-09D complete unless fresh evidence proves every item:

```text
REMOTE VERIFIED        : YES
XP LOOPBACK ONLY       : YES
TAILSCALE SERVE PRIVATE: YES
TAILSCALE FUNNEL       : NONE
PHONE -> PC PWA        : PASS
REMOTE IDENTITY GUARD  : PASS
REMOTE ORIGIN GUARD    : PASS
SESSION COOKIE GUARD   : PASS
REMOTE APPLY/DISCARD   : PASS
RECONNECT              : PASS
STALE SECOND DEVICE    : BLOCKED
FULL XP NEXT           : PASS
CP09B/CP09C            : PASS
AF-10/PWA              : PASS
WORKTREE               : CLEAN
SEG. JIWA              : UNTOUCHED
PRODUCTION DB          : UNTOUCHED
PUBLIC EXPOSURE        : NONE
```
