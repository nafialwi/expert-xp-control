from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from ..contracts import (
    AIReadiness,
    AIRequest,
    AIResponse,
    AIToolCall,
    AITransport,
    AITransportError,
    AIUsage,
    AIRoute,
)

SecretResolver = Callable[[str], str | None]
HTTPPost = Callable[
    [str, dict[str, str], dict[str, Any], int],
    Mapping[str, Any],
]


class OpenAICompatibleTransport(AITransport):
    """Minimal OpenAI-compatible non-streaming chat transport."""

    def __init__(
        self,
        secret_resolver: SecretResolver | None = None,
        http_post: HTTPPost | None = None,
        timeout: int = 60,
    ):
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive integer")
        self._secret_resolver = secret_resolver or os.environ.get
        self._http_post = http_post or self._default_http_post
        self._timeout = timeout

    def capability_name(self) -> str:
        return "openai-compatible"

    def _secret(self, route: AIRoute) -> str | None:
        try:
            value = self._secret_resolver(route.secret_env)
        except Exception:
            raise AITransportError(
                "Unable to resolve AI transport credential"
            ) from None
        if value is None:
            return None
        secret = str(value)
        return secret if secret else None

    def readiness(self, route: AIRoute) -> AIReadiness:
        try:
            secret = self._secret(route)
        except AITransportError:
            return AIReadiness(
                ready=False,
                status="NOT_READY",
                detail="AI transport credential is unavailable.",
                route_id=route.route_id,
                metadata={"transport": self.capability_name()},
            )
        if not secret:
            return AIReadiness(
                ready=False,
                status="NOT_READY",
                detail=(
                    "Credential environment variable is not available: "
                    f"{route.secret_env}"
                ),
                route_id=route.route_id,
                metadata={"transport": self.capability_name()},
            )
        return AIReadiness(
            ready=True,
            status="READY",
            detail="AI route is configured locally.",
            route_id=route.route_id,
            metadata={"transport": self.capability_name()},
        )

    def complete(
        self,
        route: AIRoute,
        request: AIRequest,
    ) -> AIResponse:
        if request.stream:
            raise AITransportError(
                "OpenAI-compatible streaming is not supported in AF-02"
            )

        secret = self._secret(route)
        if not secret:
            raise AITransportError(
                "AI transport credential is unavailable"
            )

        payload: dict[str, Any] = {
            "model": route.model,
            "messages": list(request.messages),
            "stream": False,
        }
        if request.tools:
            payload["tools"] = list(request.tools)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret}",
        }
        url = route.base_url.rstrip("/") + "/chat/completions"

        try:
            raw = self._http_post(
                url,
                headers,
                payload,
                self._timeout,
            )
        except AITransportError:
            raise
        except Exception:
            raise AITransportError(
                "OpenAI-compatible request failed"
            ) from None

        try:
            return self._normalize_response(route, raw)
        except AITransportError:
            raise
        except Exception:
            raise AITransportError(
                "OpenAI-compatible response is invalid"
            ) from None

    @staticmethod
    def _default_http_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> Mapping[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise ValueError("provider response must be an object")
        return decoded

    @classmethod
    def _normalize_response(
        cls,
        route: AIRoute,
        raw: Mapping[str, Any],
    ) -> AIResponse:
        if not isinstance(raw, Mapping):
            raise AITransportError(
                "OpenAI-compatible response is invalid"
            )

        choices = raw.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], Mapping)
        ):
            raise AITransportError(
                "OpenAI-compatible response is missing choices"
            )

        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise AITransportError(
                "OpenAI-compatible response is missing message"
            )

        content = message.get("content")
        text = content if isinstance(content, str) else ""
        tool_calls = cls._normalize_tool_calls(
            message.get("tool_calls")
        )
        usage = cls._normalize_usage(raw.get("usage"))

        provider_model = raw.get("model")
        model = (
            provider_model
            if isinstance(provider_model, str) and provider_model
            else route.model
        )

        finish_reason_raw = choice.get("finish_reason")
        finish_reason = (
            finish_reason_raw
            if isinstance(finish_reason_raw, str)
            else None
        )

        _af04_reported_model = raw.get("model")
        served_model = (
            _af04_reported_model.strip()
            if isinstance(_af04_reported_model, str)
            and _af04_reported_model.strip()
            else None
        )

        return AIResponse(
            route_id=route.route_id,
            model=model,
            served_model=served_model,
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )

    @classmethod
    def _normalize_tool_calls(
        cls,
        raw_calls: Any,
    ) -> tuple[AIToolCall, ...]:
        if raw_calls is None:
            return ()
        if not isinstance(raw_calls, list):
            raise AITransportError(
                "OpenAI-compatible tool_calls is invalid"
            )

        normalized: list[AIToolCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping):
                raise AITransportError(
                    "OpenAI-compatible tool call is invalid"
                )

            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise AITransportError(
                    "OpenAI-compatible tool call function is invalid"
                )

            call_id = raw_call.get("id")
            name = function.get("name")
            arguments_raw = function.get("arguments")

            if not isinstance(call_id, str):
                call_id = ""
            if not isinstance(name, str) or not name:
                raise AITransportError(
                    "OpenAI-compatible tool call name is invalid"
                )

            if isinstance(arguments_raw, str):
                try:
                    arguments = json.loads(arguments_raw)
                except json.JSONDecodeError as exc:
                    raise AITransportError(
                        "OpenAI-compatible tool arguments are invalid"
                    ) from exc
            elif isinstance(arguments_raw, Mapping):
                arguments = dict(arguments_raw)
            else:
                raise AITransportError(
                    "OpenAI-compatible tool arguments are invalid"
                )

            if not isinstance(arguments, dict):
                raise AITransportError(
                    "OpenAI-compatible tool arguments must be an object"
                )

            normalized.append(
                AIToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )

        return tuple(normalized)

    @staticmethod
    def _normalize_usage(raw: Any) -> AIUsage:
        if not isinstance(raw, Mapping):
            return AIUsage()

        def token_count(name: str) -> int | None:
            if name not in raw:
                return None
            value = raw.get(name)
            if isinstance(value, bool):
                return None
            if isinstance(value, int) and value >= 0:
                return value
            return None

        return AIUsage(
            input_tokens=token_count("prompt_tokens"),
            output_tokens=token_count("completion_tokens"),
            total_tokens=token_count("total_tokens"),
        )
