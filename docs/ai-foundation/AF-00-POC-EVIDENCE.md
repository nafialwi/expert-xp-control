# AF-00 — 9Router / Qwen / Gemini PoC Evidence

## Result

STATUS: PASS

The experiment demonstrated that a real coding agent can use an OpenAI-compatible 9Router endpoint backed by Gemini and perform tool-driven coding work.

## Direct 9Router Verification

Verified endpoint:

`http://127.0.0.1:20128/v1`

Model discovery succeeded.

Models observed included Gemini Flash / Lite variants.

During testing, some higher-demand models returned transient availability errors. The stable PoC route used:

`gemini/gemini-3.5-flash-lite`

Direct non-stream completion: PASS.

Direct SSE streaming: PASS.

## Tool Calling

A request declaring a `read_file` tool produced an OpenAI-format `tool_calls` response from Gemini through 9Router.

This verified that the route was capable of structured agent tool use.

## Mini-Agent Verification

A restricted throwaway mini-agent was built with only:

- `read_file`
- `write_file`
- `run_tests`

It was restricted to the dummy project and fixed a deliberately broken arithmetic implementation.

Result:

- read source: PASS
- read tests: PASS
- edit source: PASS
- execute tests: PASS

## Qwen Code Termux

Installed version:

`0.22.2-termux`

Qwen was configured to use an OpenAI-compatible endpoint pointing to 9Router.

A request capture showed Qwen sending:

- endpoint: `/v1/chat/completions`
- streaming: true
- model: `gemini/gemini-3.5-flash-lite`
- tool definitions: 11
- `stream_options.include_usage`: true
- large agent/system context

## Root Cause of Initial Qwen Failure

Replaying Qwen's exact captured request directly to 9Router exposed a Gemini schema error.

The malformed tool was:

`tts_notification`

Its parameters were effectively sent as:

`{"message": {...}}`

instead of a JSON Schema object:

`{"type":"object","properties":{"message":{...}},"required":["message"]}`

Inspection of the installed Qwen bundle found that `TTS_SCHEMA` itself was correct, but the tool constructor passed:

`TTS_SCHEMA.properties`

instead of:

`TTS_SCHEMA`

A one-line local patch corrected this.

After correction, the exact Qwen-style payload succeeded through 9Router/Gemini.

## Qwen Chat Verification

Qwen then returned successfully:

`Qwen melalui 9Router Gemini berhasil`

Observed result included:

- request errors: 0
- one API request
- model: `gemini-3.5-flash-lite`

## Real Coding-Agent Verification

Dummy project:

`~/9router-agent-test`

Broken source:

`return harga - jumlah;`

Tests expected multiplication.

RED baseline:

- tests: 2
- pass: 0
- fail: 2

Qwen Code:

- read tests
- read source
- ran failing tests
- identified incorrect subtraction
- changed source to multiplication
- ran tests again

Independent verification outside Qwen:

- tests: 2
- pass: 2
- fail: 0

Final source behavior:

`return harga * jumlah;`

## Important Limitations

This PoC does NOT yet prove:

- XP integration
- durable Qwen compatibility patching
- automatic 9Router startup
- credential recovery
- multi-provider routing
- zero-cost enforcement
- cross-device recovery
- conversational XP
- PWA UX

Those belong to later AF milestones.

## Security

No real API key belongs in Git.

The user previously used local credentials during interactive testing. Future automation must use a local secret mechanism and must never write secrets into handoff documents, Git commits or portable plaintext workspace bundles.
