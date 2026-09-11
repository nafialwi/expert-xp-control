from __future__ import annotations

import os
import re
import shutil
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit
from dataclasses import dataclass
from pathlib import Path

from .base import CapabilityAdapter
from ..redaction import redact_text


@dataclass(frozen=True)
class PostgreSQLEnvironmentStatus:
    psql_present: bool
    database_url_present: bool
    connection_checked: bool
    connection_ok: bool | None
    message: str


@dataclass(frozen=True)
class SQLExecutionResult:
    applied: bool
    returncode: int
    stdout: str
    stderr: str


_DESTRUCTIVE = re.compile(r"\b(DROP\s+(TABLE|SCHEMA|DATABASE|COLUMN)|TRUNCATE\b|DELETE\s+FROM\b)", re.I)
_DATA_CHANGE = re.compile(r"\b(INSERT\s+INTO|UPDATE\b|DELETE\s+FROM|MERGE\b)\b", re.I)
_SAFE_DDL = re.compile(r"\b(CREATE\s+(TABLE|VIEW|FUNCTION|SCHEMA|TYPE|SEQUENCE)|ALTER\s+TABLE\s+.*\bADD\b|CREATE\s+INDEX\b)\b", re.I | re.S)
_NON_TRANSACTIONAL = re.compile(r"\b(CREATE\s+INDEX\s+CONCURRENTLY|DROP\s+INDEX\s+CONCURRENTLY|VACUUM\b|REINDEX\s+CONCURRENTLY)\b", re.I)
_READ_ONLY = re.compile(r"^\s*(SELECT\b|WITH\b|EXPLAIN\b|SHOW\b)", re.I)


def _libpq_environment(database_url: str) -> dict[str, str]:
    """Convert a PostgreSQL URL to libpq environment variables.

    Keeping credentials in the child environment avoids exposing the password
    in the ``psql`` process command line / process listing.
    """
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("DATABASE_URL must be a postgresql:// URL")
    env = dict(os.environ)
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username is not None:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    database = parsed.path.lstrip("/")
    if database:
        env["PGDATABASE"] = unquote(database)
    query = parse_qs(parsed.query, keep_blank_values=False)
    query_map = {
        "sslmode": "PGSSLMODE",
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "application_name": "PGAPPNAME",
        "options": "PGOPTIONS",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
    }
    for key, env_key in query_map.items():
        values = query.get(key)
        if values:
            env[env_key] = values[-1]
    return env


def classify_sql(sql: str) -> str:
    if _NON_TRANSACTIONAL.search(sql):
        return "NON_TRANSACTIONAL"
    if _DESTRUCTIVE.search(sql):
        return "DESTRUCTIVE"
    if _DATA_CHANGE.search(sql):
        return "DATA_CHANGE"
    if _SAFE_DDL.search(sql):
        return "SAFE_DDL"
    if _READ_ONLY.search(sql):
        return "READ_ONLY"
    return "UNKNOWN"


class PostgreSQLAdapter(CapabilityAdapter):
    def __init__(self, psql_bin: str = "psql"):
        self.psql_bin = psql_bin

    def capabilities(self) -> set[str]:
        return {"postgresql-environment", "sql-classification", "psql-file"}

    def environment_status(self, check_connection: bool = True) -> PostgreSQLEnvironmentStatus:
        psql_present = (Path(self.psql_bin).exists() if "/" in self.psql_bin else shutil.which(self.psql_bin) is not None)
        url_present = bool(os.environ.get("DATABASE_URL"))
        if not check_connection:
            return PostgreSQLEnvironmentStatus(psql_present, url_present, False, None, "not checked")
        if not psql_present:
            return PostgreSQLEnvironmentStatus(False, url_present, True, False, "psql not found")
        if not url_present:
            return PostgreSQLEnvironmentStatus(True, False, True, False, "DATABASE_URL missing")
        try:
            conn_env = _libpq_environment(os.environ["DATABASE_URL"])
        except ValueError as exc:
            return PostgreSQLEnvironmentStatus(True, True, True, False, str(exc))
        try:
            result = subprocess.run(
                [self.psql_bin, "-X", "-v", "ON_ERROR_STOP=1", "-Atqc", "select 1"],
                text=True,
                capture_output=True,
                timeout=30,
                env=conn_env,
            )
        except subprocess.TimeoutExpired:
            return PostgreSQLEnvironmentStatus(True, True, True, False, "connection timeout")
        except OSError as exc:
            return PostgreSQLEnvironmentStatus(True, True, True, False, redact_text(str(exc)))
        message = redact_text(result.stderr.strip() or result.stdout.strip())
        return PostgreSQLEnvironmentStatus(True, True, True, result.returncode == 0, message)

    def apply_file(self, sql_file: Path, *, single_transaction: bool = True, timeout: int = 900) -> SQLExecutionResult:
        if not os.environ.get("DATABASE_URL"):
            return SQLExecutionResult(False, 2, "", "DATABASE_URL missing")
        try:
            conn_env = _libpq_environment(os.environ["DATABASE_URL"])
        except ValueError as exc:
            return SQLExecutionResult(False, 2, "", str(exc))
        cmd = [self.psql_bin, "-X", "-v", "ON_ERROR_STOP=1"]
        if single_transaction:
            cmd.append("--single-transaction")
        cmd += ["-f", str(Path(sql_file))]
        try:
            result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env=conn_env)
        except subprocess.TimeoutExpired:
            return SQLExecutionResult(False, 124, "", f"psql timeout after {timeout}s")
        except OSError as exc:
            return SQLExecutionResult(False, 127, "", redact_text(str(exc)))
        return SQLExecutionResult(
            applied=result.returncode == 0,
            returncode=result.returncode,
            stdout=redact_text(result.stdout),
            stderr=redact_text(result.stderr),
        )

    def run_test_file(self, sql_file: Path, *, timeout: int = 900) -> SQLExecutionResult:
        return self.apply_file(sql_file, single_transaction=False, timeout=timeout)
