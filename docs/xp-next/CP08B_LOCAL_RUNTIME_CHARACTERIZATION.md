# CP-08B — PC Local Runtime Characterization

Status: SAFE CHECKPOINT / NEEDS_ATTENTION

Base:
- branch: planning/xp-next-bootstrap
- base HEAD: 803cc21f2390e33716d259f947adda0377659f1a
- CP-08A: PASS
- stable XP 2.1.0 source: untouched

## Goal

Characterize a real PC-local zero-cost runtime using actual Qwen GGUF models,
llama.cpp serving, and the installed Hermes CLI, without claiming readiness
unless the real worker can finish a bounded isolated file task.

## Environment

Observed WSL resources:
- RAM visible to WSL: about 2.8 GiB
- swap: 1.0 GiB
- CPU: AMD Athlon 3000G, 2 cores / 4 threads
- project disk space: ample

Installed local components:
- Hermes CLI installed under the user environment
- llama.cpp single binary available as ~/.local/bin/llama
- Qwen2.5 0.5B Instruct Q4_K_M GGUF
- Qwen2.5 1.5B Instruct Q4_K_M GGUF

No paid API, 9Router, or cloud model was used for the runtime tests below.

## Qwen 1.5B runtime

The real 1.5B model loaded successfully on loopback port 18085 with:
- context: 65536
- YaRN scaling from original context 32768
- quantized K/V cache: q4_0
- one slot
- two inference threads

Observed process RSS was about 1.55 GiB and WSL swap pressure was high.

The real HermesLocalWorker readiness probe passed:
- executable found
- loopback health passed
- effective context reported 65536

However, the bounded one-file Hermes smoke task did not complete within the
480-second worker timeout.

Observed result:
- worker status: NEEDS_ATTENTION
- return code: 124
- elapsed: about 480 seconds
- changed paths: none
- source fixture remained SAFE
- review: FAIL because no mutation existed

This is a fail-closed result, not a pass.

## Qwen 0.5B runtime

The real 0.5B model also loaded successfully on loopback port 18085 with the
same 65536 context contract.

Observed process RSS was about 0.76 GiB and available WSL memory improved
substantially compared with the 1.5B runtime.

HermesLocalWorker readiness again passed, including effective context 65536.

A second bounded one-file Hermes smoke still did not complete within the
300-second worker timeout.

Observed result:
- worker status: NEEDS_ATTENTION
- return code: 124
- elapsed: about 300 seconds
- changed paths: none
- source fixture remained SAFE
- review: FAIL because no mutation existed

Therefore the smaller model reduces resource use but does not make the current
Hermes execution path operationally acceptable on this PC configuration.

## Real LocalQwenAdapter smoke

The real XP Next LocalQwenAdapter was also exercised against the real 0.5B
loopback model.

Transport/readiness checks passed and the current mechanical result validator
accepted the response because it was non-empty, local, and provider-correct.

However, the generated content was malformed/repetitive and not semantically
acceptable as useful reasoning.

This exposes an important gap:
the current verifier proves transport/contract integrity, but not semantic
quality of local reasoning.

The runtime must therefore remain NEEDS_ATTENTION even though the low-level
adapter contract returned PASS.

## Safety conclusions

The following are proven:
- real local Qwen GGUF serving works on the PC;
- 65536 effective context can be exposed over loopback;
- Hermes CLI is installed and passes XP Next readiness checks;
- XP Next refuses to claim successful worker execution when Hermes times out;
- isolated fixture source remains unchanged on worker timeout;
- no fallback to paid/cloud AI occurs;
- Segeran Jiwa projects were not used as runtime laboratories.

The following are NOT proven:
- useful semantic reasoning quality from the current 0.5B model;
- successful real Hermes file mutation on this PC;
- production-ready zero-cost local agent runtime.

## Decision

CP-08B closes as a safe characterization checkpoint with status NEEDS_ATTENTION.

Do not increase timeouts and call the runtime ready. The evidence shows that
the current hardware/runtime combination is too slow for the existing Hermes
64k execution contract.

A following bounded checkpoint should address local-runtime usability rather
than weakening safety. Candidate work includes:
- introduce a semantic/structured local-reasoning quality gate;
- evaluate a lighter worker path that does not require Hermes 64k for simple
  local edits;
- keep Hermes as an optional higher-capability worker when resources permit;
- preserve explicit provider selection and zero-cost/local-first behavior.

No production deployment, database migration, or external project mutation was
performed in CP-08B.
