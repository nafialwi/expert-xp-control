from __future__ import annotations

import sqlite3

from .job_state import JobState


SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """The database schema version is not supported by this runtime."""


_JOB_STATES_SQL = ", ".join(f"'{state.value}'" for state in JobState)
_RISKS_SQL = "'read', 'write', 'high_risk'"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    source_kind TEXT NOT NULL DEFAULT 'git' CHECK(source_kind IN ('local','git')),
    active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_projects_one_active
ON projects(active)
WHERE active = 1;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_goal TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ({_JOB_STATES_SQL})),
    risk TEXT NOT NULL DEFAULT 'read' CHECK(risk IN ({_RISKS_SQL})),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_steps (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    action TEXT NOT NULL,
    state TEXT NOT NULL,
    UNIQUE(job_id, ordinal)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    approval_class TEXT NOT NULL,
    granted INTEGER NOT NULL CHECK(granted IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT,
    processor TEXT,
    live INTEGER NOT NULL DEFAULT 0 CHECK(live IN (0,1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_points (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    source_ref TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY(scope, key)
);

CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _existing_schema_version(connection: sqlite3.Connection) -> str | None:
    meta_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if meta_exists is None:
        return None
    row = connection.execute(
        "SELECT value FROM meta WHERE key='schema_version'"
    ).fetchone()
    return None if row is None else str(row[0])


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    current = _existing_schema_version(connection)
    if current is not None and current != str(SCHEMA_VERSION):
        raise SchemaVersionError(
            f"unsupported schema version: {current}; expected {SCHEMA_VERSION}"
        )

    connection.executescript(_SCHEMA)
    connection.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}
