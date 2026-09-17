# AF-02 AI Gateway — Verification Evidence

Date: 2026-09-17  
Milestone: AF-02 — XP AI Gateway

## Baseline

- XP baseline tag: `v2.1.0`
- Baseline commit: `36a89ee`
- Feature branch: `work/af02-ai-gateway`
- Final implementation commit before evidence-only commit: `6652b50`

## Implementation Commits

1. `edfc094` — `docs(ai): lock AF-02 gateway spec and plan`
2. `d43580e` — `feat(ai): add gateway contracts`
3. `cfd1265` — `feat(ai): add validated route settings`
4. `2bc4d99` — `feat(ai): add openai compatible transport`
5. `e32594d` — `feat(ai): add route dispatch gateway`
6. `6652b50` — `feat(ai): add agent runtime boundary`

## Implemented Scope

AF-02 adds a provider-neutral AI subsystem under `src/xp/ai/` without
changing the existing GenericToolchain, package executor, workflow, or
XPConfig schema.

Implemented boundaries:

- AI contracts:
  - `AIRoute`
  - `AIRequest`
  - `AIUsage`
  - `AIToolCall`
  - `AIResponse`
  - `AIReadiness`
  - `AITransport`
  - AI error hierarchy
- Validated non-secret AI settings:
  - config version validation
  - default and explicit route selection
  - `free`, `paid`, and `unknown` cost-class representation
  - secret references by environment-variable name only
  - no API-key persistence
- OpenAI-compatible non-streaming transport:
  - injected HTTP boundary for offline tests
  - normalized text, tool calls, model, usage, and finish reason
  - missing-secret readiness handling
  - malformed tool arguments rejected
  - provider failures normalized without exposing the secret value in the
    raised `AITransportError`
- `AIGateway` route dispatch:
  - default and explicit route dispatch
  - no automatic route fallback
  - transport registry boundary
  - default OpenAI-compatible transport support
- Provider-neutral agent runtime boundary:
  - `AgentReadiness`
  - `AgentRunRequest`
  - `AgentRunResult`
  - abstract `AgentRuntime`

## Dedicated AF-02 Tests

Command:

```bash
PYTHONPATH=src python -m unittest \
  tests.test_ai_contracts \
  tests.test_ai_settings \
  tests.test_openai_compatible_transport \
  tests.test_ai_gateway \
  tests.test_agent_runtime_contract \
  -v
```

Observed result:

```text
Ran 47 tests in 0.015s

OK
AF02_TEST_EXIT=0
```

Result: **47/47 passed**.

## GenericToolchain Security Guards

Command:

```bash
PYTHONPATH=src python -m unittest \
  tests.test_generic_toolchain \
  tests.test_generic_toolchain_qwen_guards \
  -v
```

Observed result:

```text
Ran 10 tests in 0.931s

OK
GENERIC_GUARD_EXIT=0
```

Result: **10/10 passed**.

The existing guard coverage remained green for:

- command allow-list enforcement
- no shell execution
- deploy/direct-network rejection
- repository path boundary enforcement
- sensitive environment filtering
- verification source-mutation blocking
- timeout guard behavior
- optional-only onboarding behavior

## Full Regression

Command:

```bash
PYTHONPATH=src python -m unittest discover \
  -s tests \
  -p 'test_*.py' \
  -v
```

Observed result:

```text
Ran 146 tests in 17.683s

OK (skipped=1)
FULL_REGRESSION_EXIT=0
```

Result: **146 tests completed with zero failures/errors and one pre-existing
optional smoke test skipped**.

## Hygiene and Security Verification

### Diff check

Observed:

```text
DIFF_CHECK_EXIT=0
```

### Secret scan

Scan covered `src/xp/ai` and all AF-02 AI test files.

Observed:

```text
SECRET_SCAN=CLEAR
```

No actual API-key assignment was persisted in the AF-02 source or tests.

### Forbidden-scope diff

The following paths were compared against `v2.1.0`:

```text
src/xp/adapters/generic.py
src/xp/executor.py
src/xp/workflow.py
src/xp/config.py
```

Observed result: **empty diff**.

Therefore AF-02 did not modify the existing GenericToolchain guard,
package executor, workflow, or XPConfig schema.

### Working tree

Observed before evidence generation:

```text
On branch work/af02-ai-gateway
nothing to commit, working tree clean
```

## AF-02 Changed Files Before Evidence Commit

```text
A  docs/superpowers/plans/2026-09-17-af02-ai-gateway.md
A  docs/superpowers/specs/2026-09-17-af02-ai-gateway.md
A  src/xp/ai/__init__.py
A  src/xp/ai/agents/__init__.py
A  src/xp/ai/agents/base.py
A  src/xp/ai/contracts.py
A  src/xp/ai/gateway.py
A  src/xp/ai/settings.py
A  src/xp/ai/transports/__init__.py
A  src/xp/ai/transports/openai_compatible.py
A  tests/test_agent_runtime_contract.py
A  tests/test_ai_contracts.py
A  tests/test_ai_gateway.py
A  tests/test_ai_settings.py
A  tests/test_openai_compatible_transport.py
```

## Explicitly Deferred

The following are intentionally outside AF-02:

- AF-03 — Health + Compatibility
- AF-04 — Zero-Cost + Usage Policy enforcement
- AF-05 — XP Agent Dummy Integration, including a real Qwen runtime
- automatic 9Router startup
- streaming/SSE
- multi-model routing
- automatic paid fallback
- conversational XP
- PWA/browser UX

## Verification Conclusion

The AF-02 implementation reached its planned verification gates on the
implementation tree ending at `6652b50`:

- dedicated AF-02 tests: PASS
- GenericToolchain security guards: PASS
- full XP regression: PASS
- diff hygiene: PASS
- secret scan: CLEAR
- forbidden-scope diff: CLEAN

A final post-evidence-commit regression and branch-status check is still
required before integration.
