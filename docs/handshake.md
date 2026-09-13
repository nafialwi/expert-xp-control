# XP / XP+ — External AI Handshake

This document is the portable contract for an external AI preparing work for XP+.
The engine remains responsible for validation, scope enforcement, execution, verification, recovery, QA, and locking.

## Canonical XP+ schema

The engine schema is authoritative. Before creating a package spec, run `xp schema work` or `xp schema remediation`.

- Protocol version: `1`
- Operation field: `type`
- Human-QA field: `human_qa`
- Required WORK/REMEDIATION fields: `allowed_paths`, `operations`
- Project-profile required fields: `project_id`, `name`

Supported package-spec operations:

- `APPLY_PATCH`
- `ADD_FILE`
- `REPLACE_FILE`
- `DELETE_ALLOWED_FILE`
- `APPLY_DB_MIGRATION`
- `RUN_SQL_TEST`

## Package-spec rules

- Use repository-relative paths only.
- Keep `allowed_paths` as narrow as possible.
- Every operation uses the canonical `type` field.
- Human QA instructions use `human_qa`.
- Do not invent operations that are absent from `xp schema`.
- WORK and REMEDIATION packages continue to use protocol v1.
- Existing profile v1, state v1, checkpoints, and protocol-v1 manifests remain readable.

## Recommended AI workflow

1. Read the latest `xp bundle --repo <repo>` context.
2. Confirm the project identity and current milestone.
3. Run/read `xp schema work` or `xp schema remediation`.
4. Produce a declarative spec using only canonical fields and operations.
5. Let XP build, validate, apply, verify, and checkpoint the package.

The CLI schema output is the authority if any historical example disagrees with this document.

## Canonical XP schema contract

<!-- XP_SCHEMA_CONTRACT_BEGIN -->
{
  "project-profile": {
    "allowed_fields": [
      "profile_version",
      "project_id",
      "name",
      "runtimes",
      "source_adapter",
      "database_adapter",
      "verify_adapter",
      "deployment_adapter",
      "metadata"
    ],
    "profile_version": 1,
    "required": [
      "project_id",
      "name"
    ],
    "schema_name": "project-profile",
    "schema_version": "1.0"
  },
  "remediation": {
    "allowed_fields": [
      "spec_version",
      "package_type",
      "project_id",
      "run_id",
      "milestone",
      "expected_state",
      "allowed_paths",
      "operations",
      "human_qa"
    ],
    "human_qa_key": "human_qa",
    "operation_key": "type",
    "operation_types": [
      "APPLY_PATCH",
      "ADD_FILE",
      "REPLACE_FILE",
      "DELETE_ALLOWED_FILE",
      "APPLY_DB_MIGRATION",
      "RUN_SQL_TEST"
    ],
    "package_type": "REMEDIATION",
    "protocol_version": 1,
    "required": [
      "allowed_paths",
      "operations"
    ],
    "schema_name": "remediation",
    "schema_version": "1.0"
  },
  "work": {
    "allowed_fields": [
      "spec_version",
      "package_type",
      "project_id",
      "run_id",
      "milestone",
      "expected_state",
      "allowed_paths",
      "operations",
      "human_qa"
    ],
    "human_qa_key": "human_qa",
    "operation_key": "type",
    "operation_types": [
      "APPLY_PATCH",
      "ADD_FILE",
      "REPLACE_FILE",
      "DELETE_ALLOWED_FILE",
      "APPLY_DB_MIGRATION",
      "RUN_SQL_TEST"
    ],
    "package_type": "WORK",
    "protocol_version": 1,
    "required": [
      "allowed_paths",
      "operations"
    ],
    "schema_name": "work",
    "schema_version": "1.0"
  }
}
<!-- XP_SCHEMA_CONTRACT_END -->
