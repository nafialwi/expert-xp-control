from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.generic import GenericToolchainAdapter
from .project_registry import ProjectProfileError, load_project_profile


@dataclass(frozen=True)
class ProjectFinding:
    code: str
    level: str
    detail: str
    recommendation: str = ""


@dataclass(frozen=True)
class ProjectFacts:
    is_git: bool
    runtimes: tuple[str, ...]
    postgres: bool
    verify_candidates: tuple[str, ...]


@dataclass(frozen=True)
class ProjectAudit:
    status: str
    project_id: str | None
    project_name: str | None
    repo_path: str
    runtimes: tuple[str, ...]
    findings: tuple[ProjectFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "repo_path": self.repo_path,
            "runtimes": list(self.runtimes),
            "findings": [
                {
                    "code": finding.code,
                    "level": finding.level,
                    "detail": finding.detail,
                    "recommendation": finding.recommendation,
                }
                for finding in self.findings
            ],
        }


def _safe_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)
    return (data if isinstance(data, dict) else {}), None


def _package_scripts(repo: Path) -> dict[str, str]:
    data, error = _safe_json(repo / "package.json")
    if error:
        return {}
    scripts = data.get("scripts") or {}
    if not isinstance(scripts, dict):
        return {}
    return {
        str(name): str(command)
        for name, command in scripts.items()
        if isinstance(name, str) and isinstance(command, str)
    }


def discover_verify_candidates(repo: Path) -> tuple[str, ...]:
    scripts = _package_scripts(repo)
    preferred = ("verify", "check", "test", "test:all", "ci", "lint")
    return tuple(name for name in preferred if name in scripts)


def discover_project_facts(repo: Path) -> ProjectFacts:
    repo = Path(repo).expanduser().resolve()
    runtimes: list[str] = []

    if (repo / "package.json").is_file():
        runtimes.append("node")

    python_markers = (
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    )
    if any((repo / marker).is_file() for marker in python_markers):
        runtimes.append("python")
    elif any(repo.glob("*.py")):
        runtimes.append("python")

    postgres = (
        (repo / "supabase").is_dir()
        or (repo / "migrations").is_dir()
        or (repo / "postgres").is_dir()
    )

    return ProjectFacts(
        is_git=(repo / ".git").exists(),
        runtimes=tuple(dict.fromkeys(runtimes)),
        postgres=postgres,
        verify_candidates=discover_verify_candidates(repo),
    )


class ProjectDoctor:
    """Bounded, read-only readiness inspection; never invents policy."""

    def __init__(self, user_home: Path | None = None):
        self.user_home = (
            Path(user_home).expanduser().resolve()
            if user_home is not None
            else Path.home().resolve()
        )

    @staticmethod
    def _add(
        findings: list[ProjectFinding],
        code: str,
        level: str,
        detail: str,
        recommendation: str = "",
    ) -> None:
        findings.append(ProjectFinding(code, level, detail, recommendation))

    def _recovery_required(self, project_id: str | None) -> bool:
        if not project_id:
            return False
        runs = self.user_home / ".expert-workstation" / "runs"
        if not runs.is_dir():
            return False
        candidates = list(runs.glob("*/STATE.json")) + list(runs.glob("*/state.json"))
        for path in candidates[:250]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("project_id") != project_id:
                continue
            stage = str(data.get("stage") or "").upper()
            status = str(data.get("status") or "").upper()
            if (
                "RECOVERY_REQUIRED" in stage
                or "RECOVERY_REQUIRED" in status
                or stage in {"INCIDENT", "FAILED_CRITICAL"}
            ):
                return True
        return False

    def inspect(self, repo: Path) -> ProjectAudit:
        repo = Path(repo).expanduser().resolve()
        findings: list[ProjectFinding] = []

        if not repo.exists():
            self._add(
                findings,
                "SOURCE_MISSING",
                "BLOCKER",
                "Repository path does not exist.",
                "Recover or reattach source before work.",
            )
            return ProjectAudit(
                "RECOVERY_REQUIRED", None, None, str(repo), (), tuple(findings)
            )

        facts = discover_project_facts(repo)

        if not facts.is_git:
            self._add(
                findings,
                "GIT_MISSING",
                "BLOCKER",
                "No .git repository metadata was found.",
                "Recover or attach the Git-backed project source.",
            )

        if facts.runtimes:
            self._add(
                findings,
                "RUNTIME_DISCOVERED",
                "INFO",
                "Detected runtime markers: " + ", ".join(facts.runtimes),
            )
        else:
            self._add(
                findings,
                "UNKNOWN_RUNTIME",
                "WARNING",
                "No supported runtime marker was detected.",
                "Choose runtime/toolchain explicitly; XP must not guess.",
            )

        profile_path = repo / ".xp" / "project.json"
        if not profile_path.is_file():
            self._add(
                findings,
                "PROFILE_MISSING",
                "WARNING",
                "Project has no .xp/project.json profile.",
                "Review a smart-onboarding proposal before writing metadata.",
            )
            return ProjectAudit(
                "UNPROFILED", None, repo.name, str(repo), facts.runtimes, tuple(findings)
            )

        try:
            profile = load_project_profile(repo)
        except (ProjectProfileError, ValueError, json.JSONDecodeError) as exc:
            self._add(
                findings,
                "PROFILE_INVALID",
                "BLOCKER",
                f"Project profile cannot be loaded: {exc}",
                "Repair profile v1 without forced migration.",
            )
            return ProjectAudit(
                "PROFILE_INCOMPLETE",
                None,
                repo.name,
                str(repo),
                facts.runtimes,
                tuple(findings),
            )

        project_id = profile.project_id
        project_name = profile.name

        if self._recovery_required(project_id):
            self._add(
                findings,
                "RECOVERY_REQUIRED",
                "BLOCKER",
                "A current XP run indicates recovery is required.",
                "Resolve recovery before new work.",
            )
            return ProjectAudit(
                "RECOVERY_REQUIRED",
                project_id,
                project_name,
                str(repo),
                profile.runtimes or facts.runtimes,
                tuple(findings),
            )

        if not facts.is_git:
            return ProjectAudit(
                "RECOVERY_REQUIRED",
                project_id,
                project_name,
                str(repo),
                profile.runtimes or facts.runtimes,
                tuple(findings),
            )

        policies, policy_error = _safe_json(repo / ".xp" / "policies.json")
        _, compatibility_error = _safe_json(repo / ".xp" / "compatibility.json")
        incomplete = False

        if policy_error or not (repo / ".xp" / "policies.json").is_file():
            incomplete = True
            self._add(
                findings,
                "POLICY_INVALID" if policy_error else "POLICY_MISSING",
                "BLOCKER",
                (
                    f".xp/policies.json is invalid: {policy_error}"
                    if policy_error
                    else ".xp/policies.json is missing."
                ),
                "Repair/approve policy explicitly; do not invent it silently.",
            )

        if compatibility_error or not (repo / ".xp" / "compatibility.json").is_file():
            incomplete = True
            self._add(
                findings,
                "COMPATIBILITY_INVALID" if compatibility_error else "COMPATIBILITY_MISSING",
                "BLOCKER",
                (
                    f".xp/compatibility.json is invalid: {compatibility_error}"
                    if compatibility_error
                    else ".xp/compatibility.json is missing."
                ),
                "Repair explicit compatibility metadata.",
            )

        if not profile.runtimes:
            incomplete = True
            self._add(
                findings,
                "PROFILE_RUNTIME_MISSING",
                "WARNING",
                "Profile declares no runtime.",
                "Declare runtime after reviewing detected markers.",
            )

        source_verify = policies.get("source_verify") if isinstance(policies, dict) else None
        if not isinstance(source_verify, list) or not source_verify:
            incomplete = True
            self._add(
                findings,
                "CANONICAL_VERIFY_MISSING",
                "BLOCKER",
                "No canonical source verification step is declared.",
                "Choose and approve canonical verification before work.",
            )
        else:
            malformed = False
            for index, step in enumerate(source_verify):
                adapter_name = str(step.get("adapter") or "").strip() if isinstance(step, dict) else ""
                if not isinstance(step, dict) or not str(step.get("adapter") or "").strip():
                    malformed = True
                    self._add(
                        findings,
                        "CANONICAL_VERIFY_INVALID",
                        "BLOCKER",
                        f"source_verify[{index}] is not a valid adapter step.",
                        "Repair verification explicitly.",
                    )
                if adapter_name == "generic":
                    command_id = str(step.get("command") or "").strip()
                    declarations = policies.get("toolchain_commands") or {}
                    if not command_id:
                        incomplete = True
                        self._add(
                            findings,
                            "GENERIC_COMMAND_MISSING",
                            "BLOCKER",
                            f"source_verify[{index}] has no generic command id.",
                            "Reference an explicitly declared toolchain command.",
                        )
                    else:
                        try:
                            generic = GenericToolchainAdapter(
                                repo, declarations
                            )
                            generic.resolve(command_id)
                            ready = generic.readiness()
                        except Exception as exc:
                            incomplete = True
                            self._add(
                                findings,
                                "GENERIC_TOOLCHAIN_INVALID",
                                "BLOCKER",
                                f"Generic toolchain policy is invalid: {exc}",
                                "Fix the allow-listed generic toolchain declaration.",
                            )
                        else:
                            if not ready.ready:
                                incomplete = True
                                self._add(
                                    findings,
                                    "GENERIC_TOOLCHAIN_NOT_READY",
                                    "BLOCKER",
                                    ready.detail,
                                    "Install/repair the declared local toolchain.",
                                )
            if malformed:
                incomplete = True
            else:
                self._add(
                    findings,
                    "CANONICAL_VERIFY",
                    "CLEAR",
                    f"{len(source_verify)} canonical verification step(s) declared.",
                )

        if facts.postgres and profile.database_adapter != "postgresql":
            incomplete = True
            self._add(
                findings,
                "POSTGRES_PROFILE_MISMATCH",
                "WARNING",
                "PostgreSQL/Supabase markers exist but profile does not declare postgresql.",
                "Review database capability before DB work.",
            )
        elif profile.database_adapter == "postgresql":
            self._add(
                findings,
                "POSTGRES_PROFILE",
                "INFO",
                "Profile declares PostgreSQL capability.",
            )

        status = "PROFILE_INCOMPLETE" if incomplete else "WORK_READY"
        if status == "WORK_READY":
            self._add(
                findings,
                "WORK_READY",
                "CLEAR",
                "Profile and canonical verification are sufficient for XP work.",
            )

        return ProjectAudit(
            status,
            project_id,
            project_name,
            str(repo),
            profile.runtimes or facts.runtimes,
            tuple(findings),
        )
