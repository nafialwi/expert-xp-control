# AF-02 — XP AI Gateway Specification

## Status

Approved design for implementation.

- Milestone: AF-02
- Base engine: XP+ 2.1.0
- Base commit: 36a89ee
- Branch: work/af02-ai-gateway
- Baseline tests: 99 run, 0 failures, 1 skipped
- AF-01 continuity checkpoint already exists separately in expert-xp-control.

## Goal

Introduce a small, provider-neutral AI subsystem into XP without weakening
existing source, package, generic-toolchain, secret, or workflow guards.

AF-02 establishes the contracts and transport boundary only.

It does not yet make XP a conversational coding agent.

## Architectural Boundary

XP currently has strong local execution boundaries:

- GenericToolchainAdapter is allow-listed and network-blocked.
- PackageExecutor protects repository paths and secret-like files.
- XPConfig stores workstation identity/control metadata.
- WorkflowEngine controls package lifecycle.

Those components MUST NOT be weakened to support AI.

The new architecture is:

XP Core
  |
  +-- existing local adapters
  |     +-- GenericToolchainAdapter
  |
  +-- xp.ai
        |
        +-- AIGateway
        |
        +-- AITransport
        |     +-- OpenAICompatibleTransport
        |
        +-- AgentRuntime contract
              +-- no concrete Qwen implementation in AF-02

9Router is NOT an XP core dependency.

9Router is represented as one route using the generic
OpenAI-compatible transport.

## Package Structure

Create:

src/xp/ai/__init__.py
src/xp/ai/contracts.py
src/xp/ai/settings.py
src/xp/ai/gateway.py
src/xp/ai/transports/__init__.py
src/xp/ai/transports/openai_compatible.py
src/xp/ai/agents/__init__.py
src/xp/ai/agents/base.py

Tests:

tests/test_ai_contracts.py
tests/test_ai_settings.py
tests/test_openai_compatible_transport.py
tests/test_ai_gateway.py
tests/test_agent_runtime_contract.py

## Global Constraints

1. Python standard library only for AF-02.
2. No new external Python dependency.
3. No CLI command is added in AF-02.
4. GenericToolchainAdapter behavior must remain unchanged.
5. PackageExecutor behavior must remain unchanged.
6. WorkflowEngine behavior must remain unchanged.
7. XPConfig schema/version must remain unchanged.
8. No real API key may be persisted by XP.
9. No API key may appear in repr(), readiness output, exception text,
   serialized settings, or committed fixtures.
10. AI transport tests must use fake/injected HTTP behavior.
11. Unit tests must not require internet or a running 9Router.
12. Real Qwen integration is deferred to AF-05.
13. Live AI/9Router health checks are deferred to AF-03.
14. Cost enforcement is deferred to AF-04.
15. AF-02 may represent cost metadata but may not silently select paid routes.

## AI Route

An AI route is non-secret configuration.

Required fields:

- route_id
- transport
- base_url
- model
- secret_env
- cost_class

Allowed cost_class values:

- free
- paid
- unknown

Example:

{
  "version": 1,
  "default_route": "9router-gemini",
  "routes": {
    "9router-gemini": {
      "transport": "openai-compatible",
      "base_url": "http://127.0.0.1:20128/v1",
      "model": "gemini/gemini-3.5-flash-lite",
      "secret_env": "NINEROUTER_KEY",
      "cost_class": "free"
    }
  }
}

The value of NINEROUTER_KEY is never written to this file.

## Settings Location

AI settings use a separate file:

~/.expert-workstation/config/ai.json

XPConfig/workstation.json is not extended in AF-02.

Settings loading must be explicit and non-mutating.

Missing or invalid configuration must raise a structured AISettingsError.

## Settings Validation

version must equal 1.

default_route must exist in routes.

route_id must be non-empty.

transport must be non-empty.

base_url must begin with http:// or https://.

A trailing slash on base_url may be normalized away.

model must be non-empty.

secret_env must match an environment-variable identifier:

[A-Za-z_][A-Za-z0-9_]*

cost_class must be exactly one of:

free
paid
unknown

Unknown keys may be ignored only if doing so does not weaken validation of
required fields.

## Core Contracts

### AIRoute

Immutable route configuration.

Fields:

route_id: str
transport: str
base_url: str
model: str
secret_env: str
cost_class: str

repr(AIRoute) must never contain secret values because routes contain only
secret references.

### AIRequest

Fields:

messages: tuple[dict[str, Any], ...]
tools: tuple[dict[str, Any], ...] = ()
stream: bool = False

The route owns the model selection.

AF-02 does not allow callers to bypass the route by supplying an arbitrary
model in AIRequest.

### AIUsage

Fields:

input_tokens: int
output_tokens: int
total_tokens: int

Missing provider usage fields normalize to zero.

### AIToolCall

Fields:

call_id: str
name: str
arguments: dict[str, Any]

OpenAI-compatible JSON-string arguments are decoded to an object.

Malformed tool arguments raise AITransportError without exposing credentials.

### AIResponse

Fields:

route_id: str
model: str
text: str
tool_calls: tuple[AIToolCall, ...]
usage: AIUsage
finish_reason: str | None

Raw provider payloads are not stored in repr-visible response fields.

### AIReadiness

Fields:

ready: bool
status: str
detail: str
route_id: str
metadata: dict[str, Any]

Allowed status values:

READY
READY_WITH_LIMITATIONS
NOT_READY

AF-02 readiness is configuration/local-secret readiness only.

It MUST NOT perform network I/O.

## AITransport

Abstract behavior:

capability_name() -> str

readiness(route: AIRoute) -> AIReadiness

complete(route: AIRoute, request: AIRequest) -> AIResponse

The transport may resolve the secret referenced by route.secret_env through
an injected secret resolver.

The secret itself is never stored on AIRoute.

## Secret Resolution

Default secret resolution reads from os.environ.

Tests inject a fake resolver.

A missing secret produces NOT_READY during readiness.

A missing secret blocks complete().

The secret value must not appear in any error text.

## OpenAI-Compatible Transport

Transport capability name:

openai-compatible

AF-02 supports non-streaming chat completion.

Endpoint:

<base_url>/chat/completions

Request shape includes:

model
messages
tools when non-empty
stream=false

Authorization is supplied only in the outbound request header:

Authorization: Bearer <resolved-secret>

The header value must never be returned by result objects or errors.

AF-02 streaming behavior:

request.stream == True

must raise AITransportError stating that streaming is not supported in
AF-02.

## HTTP Boundary

OpenAICompatibleTransport must accept an injectable HTTP client/callable so
unit tests never contact the network.

The production default may use Python standard-library urllib.

The injectable interface returns decoded JSON-compatible mappings.

HTTP/provider failures are normalized to AITransportError.

Secrets must be redacted from failure messages.

## OpenAI Response Normalization

AF-02 consumes the first choice.

Text:

choices[0].message.content

Missing/null content normalizes to an empty string.

Tool calls:

choices[0].message.tool_calls

Each function.arguments JSON string is decoded to a dictionary.

Usage:

prompt_tokens -> input_tokens
completion_tokens -> output_tokens
total_tokens -> total_tokens

Model:

response.model if present, otherwise route.model.

Finish reason:

choices[0].finish_reason

## AIGateway

AIGateway owns route selection and transport dispatch.

Constructor consumes:

- AISettings
- transport registry

Default transport registry may include:

openai-compatible -> OpenAICompatibleTransport

Public behavior:

route(route_id: str | None = None) -> AIRoute

readiness(route_id: str | None = None) -> AIReadiness

complete(
    request: AIRequest,
    route_id: str | None = None
) -> AIResponse

If route_id is None, default_route is used.

Unknown route raises AIGatewayError.

Unknown transport raises AIGatewayError.

Gateway does not silently fall back to another route in AF-02.

Gateway does not silently change from free to paid/unknown route.

## Agent Runtime Boundary

AF-02 defines the agent contract only.

It does not implement Qwen.

Agent types:

AgentReadiness
AgentRunRequest
AgentRunResult
AgentRuntime

AgentRuntime public behavior:

name property

readiness() -> AgentReadiness

run(request: AgentRunRequest) -> AgentRunResult

This boundary exists so Qwen Code can be added later without confusing
"agent" with "model/provider/transport".

## Security Invariants

AF-02 must prove:

- settings store only secret_env reference
- secret resolver output is never serialized
- readiness never exposes secret values
- exceptions never expose secret values
- HTTP failure text is sanitized
- generic toolchain network guard remains intact
- project/package source protections remain intact
- no unit test performs external network access

## Explicit Non-Goals

AF-02 does NOT implement:

- xp ai CLI commands
- Qwen execution
- automatic 9Router startup
- 9Router-specific transport class
- multi-model selection
- provider benchmarking
- cost accounting
- token-budget enforcement
- live health checks
- streaming/SSE
- conversational XP
- PWA
- workflow WAITING_GPT rename
- automatic source editing
- deployment

## Acceptance Criteria

AF-02 is accepted only when:

1. Existing XP baseline suite still passes.
2. New AI tests pass.
3. git diff --check passes.
4. secret scan is clear.
5. AI settings represent a 9Router/Gemini route without containing a key.
6. AIGateway selects default and explicit routes correctly.
7. Unknown routes/transports fail explicitly.
8. OpenAI-compatible transport normalizes text, tool calls, usage and model.
9. Streaming is rejected explicitly.
10. Transport tests use fake HTTP.
11. Secret values are absent from repr/readiness/errors/config serialization.
12. AgentRuntime exists only as a contract.
13. No CLI/workflow/generic-executor security boundary is weakened.

## Next Milestone

AF-03 — AI Health + Compatibility

AF-03 will add live route health, environment compatibility checks, and
reproducible detection of the Qwen TTS tool-schema compatibility issue.
