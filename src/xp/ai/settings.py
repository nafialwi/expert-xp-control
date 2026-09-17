from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import AIRoute, AISettingsError


AI_SETTINGS_VERSION = 1
COST_CLASSES = frozenset({"free", "paid", "unknown"})
_SECRET_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class AISettings:
    version: int
    default_route: str
    routes: dict[str, AIRoute]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AISettings":
        if not isinstance(data, Mapping):
            raise AISettingsError("AI settings must be an object")

        version = data.get("version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != AI_SETTINGS_VERSION
        ):
            raise AISettingsError(
                f"Unsupported AI settings version: {version!r}"
            )

        default_route = str(data.get("default_route") or "").strip()
        if not default_route:
            raise AISettingsError("default_route must not be empty")

        raw_routes = data.get("routes")
        if not isinstance(raw_routes, Mapping) or not raw_routes:
            raise AISettingsError("routes must be a non-empty object")

        routes: dict[str, AIRoute] = {}
        for raw_route_id, raw in raw_routes.items():
            route_id = str(raw_route_id).strip()
            if not route_id:
                raise AISettingsError("route_id must not be empty")
            if not isinstance(raw, Mapping):
                raise AISettingsError(
                    f"route {route_id!r} must be an object"
                )

            transport = str(raw.get("transport") or "").strip()
            if not transport:
                raise AISettingsError(
                    f"route {route_id!r} transport must not be empty"
                )

            base_url = str(raw.get("base_url") or "").strip()
            if not (
                base_url.startswith("http://")
                or base_url.startswith("https://")
            ):
                raise AISettingsError(
                    f"route {route_id!r} base_url must use http or https"
                )
            base_url = base_url.rstrip("/")
            if base_url in {"http:", "https:"}:
                raise AISettingsError(
                    f"route {route_id!r} base_url is invalid"
                )

            model = str(raw.get("model") or "").strip()
            if not model:
                raise AISettingsError(
                    f"route {route_id!r} model must not be empty"
                )

            secret_env = str(raw.get("secret_env") or "").strip()
            if not _SECRET_ENV_RE.fullmatch(secret_env):
                raise AISettingsError(
                    f"route {route_id!r} secret_env is invalid"
                )

            cost_class = str(raw.get("cost_class") or "").strip()
            if cost_class not in COST_CLASSES:
                raise AISettingsError(
                    f"route {route_id!r} cost_class must be one of: "
                    + ", ".join(sorted(COST_CLASSES))
                )

            routes[route_id] = AIRoute(
                route_id=route_id,
                transport=transport,
                base_url=base_url,
                model=model,
                secret_env=secret_env,
                cost_class=cost_class,
            )

        if default_route not in routes:
            raise AISettingsError(
                f"default_route {default_route!r} is not declared"
            )

        return cls(
            version=version,
            default_route=default_route,
            routes=routes,
        )

    @classmethod
    def from_file(cls, path: Path) -> "AISettings":
        source = Path(path).expanduser()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AISettingsError(
                f"AI settings file not found: {source}"
            ) from exc
        except OSError as exc:
            raise AISettingsError(
                f"Unable to read AI settings file: {source}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise AISettingsError(
                f"Invalid JSON in AI settings file: {source}"
            ) from exc

        if not isinstance(data, Mapping):
            raise AISettingsError("AI settings file must contain an object")

        return cls.from_dict(data)

    @classmethod
    def for_home(cls, home: Path) -> "AISettings":
        root = Path(home).expanduser().resolve()
        path = root / ".expert-workstation" / "config" / "ai.json"
        return cls.from_file(path)

    def route(self, route_id: str | None = None) -> AIRoute:
        selected = self.default_route if route_id is None else str(route_id).strip()
        if not selected or selected not in self.routes:
            raise AISettingsError(f"Unknown AI route: {selected or '-'}")
        return self.routes[selected]
