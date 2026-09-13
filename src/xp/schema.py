from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any

PROTOCOL_VERSION = 1
PACKAGE_MANIFEST_REQUIRED_FIELDS = (
    "protocol_version",
    "min_xp_version",
    "package_type",
    "project_id",
    "base_fingerprint",
    "expected_state",
    "allowed_paths",
    "operations",
    "checksums",
)

PROTOCOL_V1_OPERATION_TYPES = (
    "APPLY_PATCH",
    "ADD_FILE",
    "REPLACE_FILE",
    "DELETE_ALLOWED_FILE",
    "REGISTER_MIGRATION",
    "RUN_SOURCE_VERIFY",
    "APPLY_DB_MIGRATION",
    "RUN_SQL_TEST",
    "GENERATE_CHECKPOINT",
)

ENGINE_EXECUTABLE_OPERATIONS = (
    "APPLY_PATCH",
    "ADD_FILE",
    "REPLACE_FILE",
    "DELETE_ALLOWED_FILE",
    "APPLY_DB_MIGRATION",
    "RUN_SQL_TEST",
)

SPEC_FILE_OPERATIONS = frozenset({"ADD_FILE", "REPLACE_FILE"})
SPEC_SQL_OPERATIONS = frozenset({"APPLY_DB_MIGRATION", "RUN_SQL_TEST"})
SPEC_OPERATION_TYPES = tuple(ENGINE_EXECUTABLE_OPERATIONS)

_SPEC_FIELDS = (
    "spec_version",
    "package_type",
    "project_id",
    "run_id",
    "milestone",
    "expected_state",
    "allowed_paths",
    "operations",
    "human_qa",
)

_WORK_SCHEMA = {
    "schema_name": "work",
    "schema_version": "1.0",
    "protocol_version": PROTOCOL_VERSION,
    "package_type": "WORK",
    "required": ["allowed_paths", "operations"],
    "allowed_fields": list(_SPEC_FIELDS),
    "operation_key": "type",
    "human_qa_key": "human_qa",
    "operation_types": list(SPEC_OPERATION_TYPES),
}

_REMEDIATION_SCHEMA = {
    **_WORK_SCHEMA,
    "schema_name": "remediation",
    "package_type": "REMEDIATION",
}

_PROJECT_PROFILE_SCHEMA = {
    "schema_name": "project-profile",
    "schema_version": "1.0",
    "profile_version": 1,
    "required": ["project_id", "name"],
    "allowed_fields": [
        "profile_version",
        "project_id",
        "name",
        "runtimes",
        "source_adapter",
        "database_adapter",
        "verify_adapter",
        "deployment_adapter",
        "metadata",
    ],
}


def schema_for(kind: str) -> dict[str, Any]:
    normalized = str(kind).strip().lower()
    schemas = {
        "work": _WORK_SCHEMA,
        "remediation": _REMEDIATION_SCHEMA,
        "project-profile": _PROJECT_PROFILE_SCHEMA,
    }
    if normalized not in schemas:
        raise ValueError(f"unknown schema kind: {kind}")
    return copy.deepcopy(schemas[normalized])


def schema_catalog() -> dict[str, dict[str, Any]]:
    return {
        name: schema_for(name)
        for name in ("work", "remediation", "project-profile")
    }


def _path_in_scope(path: str, allowed_paths: list[str]) -> bool:
    try:
        member = PurePosixPath(path)
    except Exception:
        return False
    if member.is_absolute() or any(part in {"", ".", ".."} for part in member.parts):
        return False
    value = str(member)
    for prefix in allowed_paths:
        clean = str(prefix).rstrip("/")
        if clean and (value == clean or value.startswith(clean + "/")):
            return True
    return False


def validate_spec_dict(spec: dict) -> list[str]:
    if not isinstance(spec, dict):
        return ["spec must be a JSON object"]

    errors: list[str] = []
    allowed_fields = set(_SPEC_FIELDS)
    for key in sorted(set(spec) - allowed_fields):
        errors.append(
            f"invalid field '{key}'; canonical fields: {', '.join(_SPEC_FIELDS)}"
        )

    if "spec_version" in spec and str(spec["spec_version"]) not in {"1", "1.0"}:
        errors.append("spec_version must be 1.0 when declared")

    package_type = str(spec.get("package_type", "WORK")).upper()
    if package_type not in {"WORK", "REMEDIATION"}:
        errors.append("package_type must be WORK or REMEDIATION")

    for required in ("allowed_paths", "operations"):
        if required not in spec:
            errors.append(f"missing canonical field '{required}'")

    allowed_paths_raw = spec.get("allowed_paths", [])
    if not isinstance(allowed_paths_raw, list) or not all(
        isinstance(value, str) and value.strip() for value in allowed_paths_raw
    ):
        errors.append("allowed_paths must be a list of non-empty repository paths")
        allowed_paths: list[str] = []
    else:
        allowed_paths = [value.strip().rstrip("/") for value in allowed_paths_raw]
        if not allowed_paths:
            errors.append("allowed_paths must not be empty")

    human_qa = spec.get("human_qa", [])
    if not isinstance(human_qa, list) or not all(isinstance(value, str) for value in human_qa):
        errors.append("human_qa must be a list of strings")

    if "project_id" in spec and not str(spec.get("project_id", "")).strip():
        errors.append("project_id must be non-empty when declared")

    operations = spec.get("operations", [])
    if not isinstance(operations, list):
        errors.append("operations must be a list")
        return errors

    supported = set(SPEC_OPERATION_TYPES)
    for index, operation in enumerate(operations):
        prefix = f"operations[{index}]"
        if not isinstance(operation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        op_type = operation.get("type")
        if not isinstance(op_type, str) or not op_type:
            errors.append(f"{prefix} missing canonical operation key 'type'")
            continue
        if op_type not in supported:
            errors.append(f"{prefix} unsupported operation '{op_type}'")
            continue

        path_required = op_type in (
            set(SPEC_FILE_OPERATIONS)
            | set(SPEC_SQL_OPERATIONS)
            | {"DELETE_ALLOWED_FILE"}
        )
        path = operation.get("path")
        if path_required and (not isinstance(path, str) or not path.strip()):
            errors.append(f"{prefix} operation {op_type} requires 'path'")
        elif isinstance(path, str) and allowed_paths and not _path_in_scope(path, allowed_paths):
            errors.append(f"{prefix} path outside allowed_paths: {path}")

        if op_type in set(SPEC_FILE_OPERATIONS) | set(SPEC_SQL_OPERATIONS):
            if not isinstance(operation.get("content"), str):
                errors.append(f"{prefix} operation {op_type} requires 'content'")
        elif op_type == "APPLY_PATCH":
            patch = operation.get("patch")
            content = operation.get("content")
            if not isinstance(patch, str) and not isinstance(content, str):
                errors.append(
                    f"{prefix} operation APPLY_PATCH requires 'patch' or 'content'"
                )

    return errors


def render_handshake_schema_section() -> str:
    work = schema_for("work")
    profile = schema_for("project-profile")
    operations = "\n".join(f"- `{name}`" for name in work["operation_types"])
    return (
        "## Canonical XP+ schema\n\n"
        "The engine schema is authoritative. Before creating a package spec, run "
        "`xp schema work` or `xp schema remediation`.\n\n"
        f"- Protocol version: `{work['protocol_version']}`\n"
        f"- Operation field: `{work['operation_key']}`\n"
        f"- Human-QA field: `{work['human_qa_key']}`\n"
        "- Required WORK/REMEDIATION fields: `allowed_paths`, `operations`\n"
        f"- Project-profile required fields: `{profile['required'][0]}`, `{profile['required'][1]}`\n\n"
        "Supported package-spec operations:\n\n"
        f"{operations}\n"
    )
