from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, fields, is_dataclass
from typing import Any

from .. import contracts as ai_contracts
from .base import AgentReadiness, AgentRunRequest, AgentRunResult


class AgentAIContractMappingError(ValueError):
    pass


def _required(field: Any) -> bool:
    return (
        field.default is MISSING
        and field.default_factory is MISSING
    )


def _message_from_prompt(prompt: str) -> Any:
    message_cls = getattr(ai_contracts, "AIMessage", None)
    if message_cls is None or not is_dataclass(message_cls):
        return {"role": "user", "content": prompt}

    kwargs: dict[str, Any] = {}
    for field in fields(message_cls):
        name = field.name.lower()
        if name == "role":
            kwargs[field.name] = "user"
        elif name in {"content", "text", "message"}:
            kwargs[field.name] = prompt
        elif _required(field):
            raise AgentAIContractMappingError(
                f"unsupported required AIMessage field: {field.name}"
            )
    return message_cls(**kwargs)


def encode_agent_request(
    request: AgentRunRequest,
    *,
    model: str | None = None,
) -> Any:
    if not isinstance(request, AgentRunRequest):
        raise TypeError("request must be AgentRunRequest")

    prompt = request.prompt
    if not isinstance(prompt, str) or not prompt:
        raise AgentAIContractMappingError("agent prompt must be non-empty")

    request_cls = ai_contracts.AIRequest
    if not is_dataclass(request_cls):
        raise AgentAIContractMappingError("AIRequest must be a dataclass")

    kwargs: dict[str, Any] = {}
    for field in fields(request_cls):
        name = field.name.lower()

        if name in {"prompt", "input", "text", "query"}:
            kwargs[field.name] = prompt
        elif name == "messages":
            kwargs[field.name] = (_message_from_prompt(prompt),)
        elif name == "model":
            if model is None or not isinstance(model, str) or not model.strip():
                raise AgentAIContractMappingError(
                    "explicit model is required by AIRequest"
                )
            kwargs[field.name] = model.strip()
        elif name == "stream":
            kwargs[field.name] = False
        elif name == "tools" and _required(field):
            kwargs[field.name] = ()
        elif name == "metadata" and _required(field):
            kwargs[field.name] = {}
        elif _required(field):
            raise AgentAIContractMappingError(
                f"unsupported required AIRequest field: {field.name}"
            )

    return request_cls(**kwargs)


def _extract_text(response: Any) -> str:
    for name in ("content", "output", "text"):
        if hasattr(response, name):
            value = getattr(response, name)
            if isinstance(value, str):
                return value

    if hasattr(response, "message"):
        message = getattr(response, "message")
        if isinstance(message, str):
            return message
        for name in ("content", "text"):
            if hasattr(message, name):
                value = getattr(message, name)
                if isinstance(value, str):
                    return value

    raise AgentAIContractMappingError(
        "AIResponse does not contain textual output"
    )


def decode_ai_response(response: Any) -> AgentRunResult:
    if not isinstance(response, ai_contracts.AIResponse):
        raise TypeError("response must be AIResponse")

    output = _extract_text(response)
    return AgentRunResult(
        status="COMPLETED",
        output=output,
        returncode=0,
    )


def decode_ai_readiness(readiness: Any) -> AgentReadiness:
    if not isinstance(readiness, ai_contracts.AIReadiness):
        raise TypeError("readiness must be AIReadiness")

    raw_status = getattr(readiness, "status", None)
    raw_ready = getattr(readiness, "ready", None)

    if isinstance(raw_ready, bool):
        ready = raw_ready
    elif isinstance(raw_status, str):
        ready = raw_status.strip().upper() in {
            "READY",
            "AVAILABLE",
            "OK",
            "PASS",
        }
    else:
        raise AgentAIContractMappingError(
            "AIReadiness has no usable ready/status value"
        )

    if isinstance(raw_status, str) and raw_status.strip():
        status = raw_status.strip()
    else:
        status = "READY" if ready else "NOT_READY"

    detail = ""
    for name in ("detail", "reason", "message"):
        value = getattr(readiness, name, None)
        if isinstance(value, str):
            detail = value
            break

    metadata = getattr(readiness, "metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}

    return AgentReadiness(
        ready=ready,
        status=status,
        detail=detail,
        metadata=dict(metadata),
    )


__all__ = [
    "AgentAIContractMappingError",
    "decode_ai_readiness",
    "decode_ai_response",
    "encode_agent_request",
]
