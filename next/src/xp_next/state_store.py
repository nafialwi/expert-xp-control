from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .job_state import JobState, can_transition
from .state_schema import initialize_schema


class StateStoreError(RuntimeError):
    pass


class ProjectNotFound(StateStoreError):
    pass


class JobNotFound(StateStoreError):
    pass


class InvalidJobTransition(StateStoreError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


class StateStore:
    """Small SQLite-backed canonical state store for XP Next."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        initialize_schema(self.connection)

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def register_project(
        self,
        project_id: str,
        name: str,
        root_path: str,
        *,
        source_kind: str = "git",
    ) -> dict[str, object]:
        if not project_id.strip() or not name.strip() or not root_path.strip():
            raise ValueError("project id, name, and root_path must not be empty")
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO projects(
                    id, name, root_path, source_kind, active, created_at, updated_at
                ) VALUES(?,?,?,?,0,?,?)
                """,
                (
                    project_id.strip(),
                    name.strip(),
                    root_path.strip(),
                    source_kind.strip() or "git",
                    now,
                    now,
                ),
            )
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT * FROM projects ORDER BY id"
        ).fetchall()
        return [
            result
            for row in rows
            if (result := _as_dict(row)) is not None
        ]

    def get_project(self, project_id: str) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE id=?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        result = _as_dict(row)
        assert result is not None
        return result

    def get_active_project(self) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT * FROM projects WHERE active=1"
        ).fetchone()
        return _as_dict(row)

    def set_active_project(self, project_id: str) -> dict[str, object]:
        # Validate before clearing the current active project.
        self.get_project(project_id)
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                "UPDATE projects SET active=0, updated_at=? WHERE active=1",
                (now,),
            )
            self.connection.execute(
                "UPDATE projects SET active=1, updated_at=? WHERE id=?",
                (now, project_id),
            )
        return self.get_project(project_id)

    def create_job(
        self,
        job_id: str,
        project_id: str,
        user_goal: str,
        *,
        risk: str = "read",
    ) -> dict[str, object]:
        if not job_id.strip() or not user_goal.strip():
            raise ValueError("job id and user_goal must not be empty")
        self.get_project(project_id)
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO jobs(
                    id, project_id, user_goal, state, risk, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    job_id.strip(),
                    project_id,
                    user_goal.strip(),
                    JobState.DRAFT.value,
                    risk,
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        result = _as_dict(row)
        assert result is not None
        return result

    def transition_job(
        self,
        job_id: str,
        target: JobState,
    ) -> dict[str, object]:
        if not isinstance(target, JobState):
            raise TypeError("target must be JobState")

        job = self.get_job(job_id)
        current = JobState(str(job["state"]))
        if not can_transition(current, target):
            raise InvalidJobTransition(
                f"invalid transition: {current.value} -> {target.value}"
            )

        now = _utc_now()
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE jobs SET state=?, updated_at=? WHERE id=? AND state=?",
                (target.value, now, job_id, current.value),
            )
            if cursor.rowcount != 1:
                raise InvalidJobTransition(
                    "job state changed concurrently; retry from fresh state"
                )
        return self.get_job(job_id)

    def record_approval(
        self,
        approval_id: str,
        *,
        job_id: str,
        approval_class: str,
        granted: bool,
    ) -> dict[str, object]:
        if not approval_id.strip() or not approval_class.strip():
            raise ValueError("approval id and class must not be empty")
        self.get_job(job_id)
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO approvals(id, job_id, approval_class, granted, created_at)
                VALUES(?,?,?,?,?)
                """,
                (
                    approval_id.strip(),
                    job_id,
                    approval_class.strip(),
                    1 if granted else 0,
                    now,
                ),
            )
        row = self.connection.execute(
            "SELECT * FROM approvals WHERE id=?",
            (approval_id.strip(),),
        ).fetchone()
        result = _as_dict(row)
        assert result is not None
        return result

    def list_approvals(self, job_id: str) -> list[dict[str, object]]:
        self.get_job(job_id)
        rows = self.connection.execute(
            "SELECT * FROM approvals WHERE job_id=? ORDER BY created_at, id",
            (job_id,),
        ).fetchall()
        return [result for row in rows if (result := _as_dict(row)) is not None]

    def record_activity(
        self,
        activity_id: str,
        *,
        job_id: str | None,
        category: str,
        action: str,
        status: str,
        summary: str,
        source: str | None = None,
        processor: str | None = None,
        live: bool = False,
    ) -> dict[str, object]:
        values = (activity_id, category, action, status, summary)
        if any(not value.strip() for value in values):
            raise ValueError("activity id/category/action/status/summary must not be empty")
        if job_id is not None:
            self.get_job(job_id)
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO activities(
                    id, job_id, category, action, status, summary,
                    source, processor, live, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    activity_id.strip(),
                    job_id,
                    category.strip(),
                    action.strip(),
                    status.strip(),
                    summary.strip(),
                    source,
                    processor,
                    1 if live else 0,
                    now,
                ),
            )
        row = self.connection.execute(
            "SELECT * FROM activities WHERE id=?",
            (activity_id.strip(),),
        ).fetchone()
        result = _as_dict(row)
        assert result is not None
        return result

    def list_activities(self, job_id: str) -> list[dict[str, object]]:
        self.get_job(job_id)
        rows = self.connection.execute(
            "SELECT * FROM activities WHERE job_id=? ORDER BY created_at, id",
            (job_id,),
        ).fetchall()
        return [result for row in rows if (result := _as_dict(row)) is not None]

    def record_recovery_point(
        self,
        recovery_id: str,
        *,
        project_id: str,
        source_ref: str,
        job_id: str | None = None,
    ) -> dict[str, object]:
        if not recovery_id.strip() or not source_ref.strip():
            raise ValueError("recovery id and source_ref must not be empty")
        self.get_project(project_id)
        if job_id is not None:
            job = self.get_job(job_id)
            if str(job["project_id"]) != project_id:
                raise ValueError("recovery job belongs to another project")
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO recovery_points(id, project_id, job_id, source_ref, created_at)
                VALUES(?,?,?,?,?)
                """,
                (
                    recovery_id.strip(),
                    project_id,
                    job_id,
                    source_ref.strip(),
                    now,
                ),
            )
        row = self.connection.execute(
            "SELECT * FROM recovery_points WHERE id=?",
            (recovery_id.strip(),),
        ).fetchone()
        result = _as_dict(row)
        assert result is not None
        return result

    def list_recovery_points(
        self,
        *,
        project_id: str | None = None,
        job_id: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[str] = []
        if project_id is not None:
            self.get_project(project_id)
            clauses.append("project_id=?")
            params.append(project_id)
        if job_id is not None:
            self.get_job(job_id)
            clauses.append("job_id=?")
            params.append(job_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM recovery_points{where} ORDER BY created_at, id",
            tuple(params),
        ).fetchall()
        return [result for row in rows if (result := _as_dict(row)) is not None]
