# AF-08 Hybrid Intelligence & Multi-AI Routing

## Purpose

AF-08 formalizes provider/model/worker selection policy inside canonical XP+.

It does not import the external `xp_hybrid.py` pilot. The pilot remains
historical evidence and a UI experiment.

## Core policy

- deterministic work stays deterministic;
- AI and worker routes require explicit selection;
- cloud routes require explicit LIVE mode;
- worker mutation requires WORKER mode and permission;
- cost/quota/readiness/privacy are gates, never reasons for silent fallback;
- route failure remains on the selected identity and becomes
  `NEEDS_ATTENTION`;
- provider/model identity is observable;
- source provenance is independent from provider/model;
- route evaluation performs no network access.

## Provider failures

Canonical categories:

- quota/rate limit;
- authentication;
- temporary unavailable;
- timeout;
- generic provider error.

A 9Router outer 503 carrying an upstream 429/quota message is classified as
quota/rate-limit.

## External service policy

An explicit 9Router loopback observation may be recorded at closure. No
background health loop is added. Successful cloud inference is not a closure
dependency because AF-05 already established real inference and AF-09 owns the
real project pilot.
