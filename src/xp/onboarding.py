from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .project_registry import ProjectIdentityError, ProjectProfile, ProjectRegistry, load_project_profile


class OnboardingError(RuntimeError):
    pass


_ALLOWED_PROFILE_FILES = {".xp/project.json", ".xp/policies.json", ".xp/compatibility.json"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if result.returncode != 0:
        raise OnboardingError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _safe_zip_name(name: str) -> PurePosixPath:
    if "\\" in name:
        raise OnboardingError("unsafe profile archive path")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise OnboardingError("unsafe profile archive path")
    return p


@dataclass(frozen=True)
class ProfilePackageManifest:
    project_id: str
    project_name: str
    expected_branch: str
    expected_head_prefix: str
    required_file_hashes: dict[str, str]
    files: dict[str, str]


class ProjectOnboarder:
    def __init__(self, user_home: Path):
        self.user_home = Path(user_home).expanduser().resolve()

    def _inspect(self, package: Path) -> ProfilePackageManifest:
        try:
            with zipfile.ZipFile(package) as zf:
                data = json.loads(zf.read("manifest.json").decode("utf-8"))
                if data.get("profile_protocol_version") != 1 or data.get("package_type") != "PROJECT_PROFILE":
                    raise OnboardingError("unsupported project profile package")
                for info in zf.infolist():
                    _safe_zip_name(info.filename)
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode):
                        raise OnboardingError("symlink is not allowed in profile package")
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise OnboardingError("invalid project profile package") from exc
        files = {str(k): str(v) for k, v in dict(data.get("files") or {}).items()}
        if set(files) != _ALLOWED_PROFILE_FILES:
            raise OnboardingError("profile package may only contain the three .xp metadata files")
        return ProfilePackageManifest(
            project_id=str(data["project_id"]),
            project_name=str(data["project_name"]),
            expected_branch=str(data["expected_branch"]),
            expected_head_prefix=str(data["expected_head_prefix"]),
            required_file_hashes={str(k): str(v) for k, v in dict(data.get("required_file_hashes") or {}).items()},
            files=files,
        )

    def validate_target(self, repo: Path, package: Path) -> ProfilePackageManifest:
        repo = Path(repo).expanduser().resolve()
        package = Path(package).expanduser().resolve()
        if not (repo / ".git").exists():
            raise OnboardingError("target is not a Git repository")
        manifest = self._inspect(package)
        branch = _git(repo, "branch", "--show-current")
        head = _git(repo, "rev-parse", "HEAD")
        dirty_before = _git(repo, "status", "--porcelain")
        if dirty_before:
            raise OnboardingError("repository must be clean before XP onboarding")
        if branch != manifest.expected_branch:
            raise OnboardingError(f"branch mismatch: expected {manifest.expected_branch}, got {branch}")
        if not head.startswith(manifest.expected_head_prefix):
            raise OnboardingError("HEAD does not match the approved profile package")
        for rel, expected in manifest.required_file_hashes.items():
            safe = _safe_zip_name(rel)
            target = (repo / Path(*safe.parts)).resolve()
            if repo not in target.parents or not target.is_file():
                raise OnboardingError(f"required anchor missing: {rel}")
            if _sha(target) != expected:
                raise OnboardingError(f"anchor hash mismatch: {rel}")
        if (repo / ".xp").exists():
            raise OnboardingError("project already contains .xp metadata; use profile audit/update instead")
        return manifest

    def apply(self, repo: Path, package: Path) -> ProjectProfile:
        repo = Path(repo).expanduser().resolve()
        package = Path(package).expanduser().resolve()
        manifest = self.validate_target(repo, package)
        xp_dir = repo / ".xp"
        staged: dict[str, bytes] = {}
        with zipfile.ZipFile(package) as zf:
            for rel, expected in manifest.files.items():
                data = zf.read("files/" + rel)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise OnboardingError(f"profile file checksum mismatch: {rel}")
                staged[rel] = data
        try:
            project_data = json.loads(staged[".xp/project.json"].decode("utf-8"))
            candidate_profile = ProjectProfile.from_dict(project_data)
            ProjectRegistry.for_home(self.user_home).assert_can_register(candidate_profile)
        except (ProjectIdentityError, ValueError, json.JSONDecodeError) as exc:
            raise OnboardingError(f"project registry conflict: {exc}") from exc
        try:
            xp_dir.mkdir()
            for rel, data in staged.items():
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + f".xp-{os.getpid()}.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, target)
            profile = load_project_profile(repo)
            if profile.project_id != manifest.project_id or profile.name != manifest.project_name:
                raise OnboardingError("installed profile identity does not match package manifest")
            _git(repo, "add", ".xp")
            _git(repo, "commit", "-m", f"chore(xp): add XP project profile for {manifest.project_id}")
            ProjectRegistry.for_home(self.user_home).register(profile, repo)
            return profile
        except Exception:
            if xp_dir.exists():
                import shutil
                shutil.rmtree(xp_dir, ignore_errors=True)
            raise

@dataclass(frozen=True)
class SmartOnboardingProposal:
    status: str
    repo_path: str
    project_id: str
    project_name: str
    runtimes: tuple[str, ...]
    verify_candidates: tuple[str, ...]
    recommended_verify: str | None
    profile: dict
    policies: dict
    compatibility: dict
    findings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "repo_path": self.repo_path,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "runtimes": list(self.runtimes),
            "verify_candidates": list(self.verify_candidates),
            "recommended_verify": self.recommended_verify,
            "profile": self.profile,
            "policies": self.policies,
            "compatibility": self.compatibility,
            "findings": list(self.findings),
        }


class SmartProjectOnboarder:
    def __init__(self, user_home: Path):
        self.user_home = Path(user_home).expanduser().resolve()

    @staticmethod
    def _slug(value: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "project"

    def propose(self, repo: Path) -> SmartOnboardingProposal:
        from .project_doctor import ProjectDoctor, discover_project_facts

        repo = Path(repo).expanduser().resolve()
        if not repo.is_dir():
            raise OnboardingError("target repository does not exist")

        if (repo / ".xp" / "project.json").is_file():
            audit = ProjectDoctor(self.user_home).inspect(repo)
            return SmartOnboardingProposal(
                "ALREADY_PROFILED",
                str(repo),
                audit.project_id or self._slug(repo.name),
                audit.project_name or repo.name,
                audit.runtimes,
                (),
                None,
                {},
                {},
                {},
                ("Existing .xp profile detected; audit it instead.",),
            )

        if not (repo / ".git").exists():
            raise OnboardingError("smart onboarding requires a Git repository")

        facts = discover_project_facts(repo)
        project_id = self._slug(repo.name)
        candidates = facts.verify_candidates
        recommended = candidates[0] if len(candidates) == 1 else None
        findings: list[str] = []
        status = "PROPOSAL_READY"

        if not facts.runtimes:
            status = "USER_CHOICE_REQUIRED"
            findings.append("UNKNOWN_RUNTIME: choose runtime/toolchain explicitly.")
        if len(candidates) > 1:
            status = "USER_CHOICE_REQUIRED"
            findings.append("Multiple verification scripts are plausible; choose one.")
        elif not candidates:
            status = "USER_CHOICE_REQUIRED"
            findings.append("No canonical verification command can be inferred safely.")

        verify_steps = (
            [{"adapter": "node", "script": recommended}]
            if recommended and "node" in facts.runtimes
            else []
        )

        profile = {
            "profile_version": 1,
            "project_id": project_id,
            "name": repo.name,
            "runtimes": list(facts.runtimes),
            "source_adapter": "git",
            "database_adapter": "postgresql" if facts.postgres else None,
            "verify_adapter": "npm-script" if verify_steps else None,
            "deployment_adapter": None,
            "metadata": {"onboarding": "xp-plus-smart-proposal"},
        }
        policies = {
            "protected_branches": ["main", "master"],
            "allowed_branch_prefixes": ["work/", "xp/recovery/"],
            "source_verify": verify_steps,
            "database": None,
            "deployment": {
                "production": "DISABLED",
                "reason": "not inferred by smart onboarding",
            },
        }

        required = ["git"]
        if "node" in facts.runtimes:
            required += ["node", "npm"]
        if "python" in facts.runtimes:
            required += ["python"]
        compatibility = {
            "required_commands": list(dict.fromkeys(required)),
            "database_commands": ["psql"] if facts.postgres else [],
        }

        return SmartOnboardingProposal(
            status,
            str(repo),
            project_id,
            repo.name,
            facts.runtimes,
            candidates,
            recommended,
            profile,
            policies,
            compatibility,
            tuple(findings),
        )

    def apply(
        self,
        repo: Path,
        proposal: SmartOnboardingProposal,
        *,
        approved: bool,
        verify_choice: str | None = None,
    ) -> ProjectProfile:
        repo = Path(repo).expanduser().resolve()
        if not approved:
            raise OnboardingError("explicit approval is required")
        if proposal.status == "ALREADY_PROFILED":
            raise OnboardingError("project is already profiled; audit it instead")

        selected = verify_choice or proposal.recommended_verify
        if proposal.status == "USER_CHOICE_REQUIRED":
            if not selected or selected not in proposal.verify_candidates:
                raise OnboardingError("explicit verify choice is required")

        profile = dict(proposal.profile)
        policies = json.loads(json.dumps(proposal.policies))
        if selected:
            if "node" not in proposal.runtimes:
                raise OnboardingError("selected npm verify requires node runtime")
            policies["source_verify"] = [{"adapter": "node", "script": selected}]
            profile["verify_adapter"] = "npm-script"

        if not profile.get("runtimes"):
            raise OnboardingError("runtime remains unknown; XP must not invent it")
        if not policies.get("source_verify"):
            raise OnboardingError("canonical verification remains unresolved")

        xp_dir = repo / ".xp"
        if xp_dir.exists():
            raise OnboardingError(".xp already exists; audit/update instead")

        xp_dir.mkdir()
        try:
            for name, payload in {
                "project.json": profile,
                "policies.json": policies,
                "compatibility.json": proposal.compatibility,
            }.items():
                target = xp_dir / name
                tmp = target.with_name(target.name + f".xp-{os.getpid()}.tmp")
                tmp.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                os.replace(tmp, target)
            installed = load_project_profile(repo)
            ProjectRegistry.for_home(self.user_home).register(installed, repo)
            return installed
        except Exception:
            import shutil
            shutil.rmtree(xp_dir, ignore_errors=True)
            raise
