# AF-02 AI Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-neutral AI Gateway foundation to XP+ without weakening existing execution, secret, package, workflow, or generic-toolchain protections.

**Architecture:** Add a separate `xp.ai` package with immutable AI contracts, validated non-secret route settings, an OpenAI-compatible transport, a route-dispatching gateway, and an abstract agent runtime boundary. 9Router is configuration for the generic OpenAI-compatible transport, not a core dependency.

**Tech Stack:** Python 3 standard library, dataclasses, abc, json, urllib, unittest.

**Spec:** `docs/superpowers/specs/2026-09-17-af02-ai-gateway.md`

## Global Constraints

- Base engine: XP+ 2.1.0 at `36a89ee`.
- Standard library only; no new dependency.
- No new CLI command in AF-02.
- Do not modify GenericToolchainAdapter, PackageExecutor, WorkflowEngine, or XPConfig behavior/schema.
- Never persist API secret values.
- Unit tests must not require internet or a live 9Router.
- Streaming is unsupported in AF-02.
- Live health is AF-03, cost enforcement AF-04, real Qwen execution AF-05.

---

## Task 1 — AI Core Contracts

**Create**
- `src/xp/ai/__init__.py`
- `src/xp/ai/contracts.py`
- `tests/test_ai_contracts.py`

**Produce**
`AIError`, `AISettingsError`, `AITransportError`, `AIGatewayError`,
`AIRoute`, `AIRequest`, `AIUsage`, `AIToolCall`, `AIResponse`,
`AIReadiness`, `AITransport`.

- [ ] Write failing tests proving AIRoute is immutable; AIRequest defaults
  `tools=()` and `stream=False`; AIUsage defaults counters to zero;
  AIReadiness is structured; AITransport is abstract.
- [ ] Run:
  `PYTHONPATH=src python -m unittest tests.test_ai_contracts -v`
  and confirm RED.
- [ ] Implement frozen dataclasses and abstract transport contract.
- [ ] Re-run and confirm PASS.
- [ ] Commit:
  `git commit -m "feat(ai): add gateway contracts"`

Required signatures:

```python
@dataclass(frozen=True)
class AIRoute:
    route_id: str
    transport: str
    base_url: str
    model: str
    secret_env: str
    cost_class: str

@dataclass(frozen=True)
class AIRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    stream: bool = False

@dataclass(frozen=True)
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

@dataclass(frozen=True)
class AIToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class AIResponse:
    route_id: str
    model: str
    text: str
    tool_calls: tuple[AIToolCall, ...]
    usage: AIUsage
    finish_reason: str | None = None

@dataclass(frozen=True)
class AIReadiness:
    ready: bool
    status: str
    detail: str
    route_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

`AITransport` must define abstract `capability_name()`, `readiness(route)`,
and `complete(route, request)`.

---

## Task 2 — Validated Non-Secret AI Settings

**Create**
- `src/xp/ai/settings.py`
- `tests/test_ai_settings.py`

**Produce**
`AISettings`, `from_dict`, `from_file`, `for_home`, `route`.

- [ ] Write RED tests for invalid version, missing/unknown default route,
  empty model, invalid base URL, invalid `secret_env`, invalid `cost_class`,
  valid 9Router route, default/explicit route lookup, and secret-safe repr.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_ai_settings -v`.
- [ ] Implement:
  - `AI_SETTINGS_VERSION = 1`
  - cost classes `free`, `paid`, `unknown`
  - secret env regex `^[A-Za-z_][A-Za-z0-9_]*$`
  - settings path `<home>/.expert-workstation/config/ai.json`
  - no automatic file creation.
- [ ] Re-run and confirm PASS.
- [ ] Commit:
  `git commit -m "feat(ai): add validated route settings"`

`AISettings`:

```python
@dataclass(frozen=True)
class AISettings:
    version: int
    default_route: str
    routes: dict[str, AIRoute]
```

---

## Task 3 — OpenAI-Compatible Transport

**Create**
- `src/xp/ai/transports/__init__.py`
- `src/xp/ai/transports/openai_compatible.py`
- `tests/test_openai_compatible_transport.py`

**Produce** `OpenAICompatibleTransport`.

Constructor:

```python
OpenAICompatibleTransport(
    secret_resolver=None,
    http_post=None,
    timeout: int = 60,
)
```

- [ ] RED tests:
  - missing secret => `NOT_READY`
  - present secret => `READY`
  - readiness does no HTTP
  - secret absent from repr/errors
  - `stream=True` => `AITransportError`
  - fake HTTP response normalizes text/tool calls/usage/model/finish reason.
- [ ] Implement standard-library urllib POST to
  `{base_url}/chat/completions`, with Authorization header only in outbound
  request.
- [ ] Request body includes route model, messages, optional tools,
  `stream=False`.
- [ ] Provider/HTTP failures normalize to secret-free `AITransportError`.
- [ ] Decode OpenAI function `arguments` JSON to dict; malformed/non-object
  arguments raise `AITransportError`.
- [ ] Missing usage => zeros; missing response model => route model.
- [ ] Run:
  `PYTHONPATH=src python -m unittest tests.test_openai_compatible_transport -v`
- [ ] Commit:
  `git commit -m "feat(ai): add openai compatible transport"`

---

## Task 4 — AI Gateway Route Dispatch

**Create**
- `src/xp/ai/gateway.py`
- `tests/test_ai_gateway.py`

**Modify**
- `src/xp/ai/__init__.py`

**Produce** `AIGateway(settings, transports=None)` with:
`route(route_id=None)`, `readiness(route_id=None)`,
`complete(request, route_id=None)`.

- [ ] RED tests for default route, explicit route, unknown route,
  unknown transport, exact delegation, no fallback, and no silent
  free-to-paid/unknown substitution.
- [ ] Implement default registry:
  `{"openai-compatible": OpenAICompatibleTransport()}`.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_ai_gateway -v`.
- [ ] Commit:
  `git commit -m "feat(ai): add route dispatch gateway"`

---

## Task 5 — Agent Runtime Boundary

**Create**
- `src/xp/ai/agents/__init__.py`
- `src/xp/ai/agents/base.py`
- `tests/test_agent_runtime_contract.py`

**Produce**
`AgentReadiness`, `AgentRunRequest`, `AgentRunResult`, `AgentRuntime`.

Required types:

```python
@dataclass(frozen=True)
class AgentReadiness:
    ready: bool
    status: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AgentRunRequest:
    prompt: str
    cwd: Path | None = None

@dataclass(frozen=True)
class AgentRunResult:
    status: str
    output: str
    returncode: int | None = None
```

`AgentRuntime` is abstract with `name`, `readiness()`, and `run(request)`.

- [ ] Write RED tests proving abstract instantiation is blocked and a fake
  runtime satisfies the contract.
- [ ] Implement boundary only; no Qwen-specific code.
- [ ] Run:
  `PYTHONPATH=src python -m unittest tests.test_agent_runtime_contract -v`
- [ ] Commit:
  `git commit -m "feat(ai): add agent runtime boundary"`

---

## Task 6 — Security and Regression Gate

- [ ] Run all new AF-02 tests:

```bash
PYTHONPATH=src python -m unittest   tests.test_ai_contracts   tests.test_ai_settings   tests.test_openai_compatible_transport   tests.test_ai_gateway   tests.test_agent_runtime_contract -v
```

- [ ] Re-run generic guard tests:

```bash
PYTHONPATH=src python -m unittest   tests.test_generic_toolchain   tests.test_generic_toolchain_qwen_guards -v
```

- [ ] Full regression:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: 0 failures; existing optional real-project smoke may remain skipped.

- [ ] Hygiene:
  `git diff --check`
  and inspect `git status --short`.

- [ ] Secret scan over `src/xp/ai` and `tests/test_ai_*`; actual secret
  assignments must be absent.

- [ ] Forbidden-scope diff must be empty:

```bash
git diff v2.1.0 --   src/xp/adapters/generic.py   src/xp/executor.py   src/xp/workflow.py   src/xp/config.py
```

- [ ] After every gate passes, create:
  `docs/superpowers/evidence/2026-09-17-af02-ai-gateway.md`
  recording base/final commit, new tests, full regression, secret scan,
  forbidden-scope diff, implemented scope, and deferred AF-03/04/05 scope.
- [ ] Commit evidence:
  `git commit -m "docs(ai): record AF-02 verification evidence"`

## Self-Review

Covered: provider-neutral gateway, OpenAI-compatible route, no 9Router
hard-code, separate agent boundary, no credential persistence, no weakening
of GenericToolchain/workflow/XPConfig/package executor, fake HTTP testing,
non-streaming scope, no silent fallback, cost metadata representation, and
deferral of Qwen/live-health/cost enforcement.

## Completion Condition

AF-02 is complete only after Task 6 passes in full.
Do not start AF-03 from a partially green AF-02 branch.
