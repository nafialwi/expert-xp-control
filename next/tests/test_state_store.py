from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
import unittest

from xp_next.job_state import JobState
from xp_next.state_schema import SchemaVersionError, initialize_schema
from xp_next.state_store import (
    InvalidJobTransition,
    JobNotFound,
    ProjectNotFound,
    StateStore,
)


class StateSchemaConstraintTests(unittest.TestCase):
    def test_only_one_project_can_be_active(self):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)
        now = "2026-09-20T00:00:00+00:00"
        conn.execute(
            "insert into projects(id,name,root_path,active,created_at,updated_at) values(?,?,?,?,?,?)",
            ("p1", "One", "/one", 1, now, now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into projects(id,name,root_path,active,created_at,updated_at) values(?,?,?,?,?,?)",
                ("p2", "Two", "/two", 1, now, now),
            )

    def test_invalid_job_state_is_rejected_by_database(self):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)
        now = "2026-09-20T00:00:00+00:00"
        conn.execute(
            "insert into projects(id,name,root_path,created_at,updated_at) values(?,?,?,?,?)",
            ("p1", "One", "/one", now, now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into jobs(id,project_id,user_goal,state,created_at,updated_at) values(?,?,?,?,?,?)",
                ("j1", "p1", "goal", "WAITING_GPT", now, now),
            )

    def test_invalid_job_risk_is_rejected_by_database(self):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)
        now = "2026-09-20T00:00:00+00:00"
        conn.execute(
            "insert into projects(id,name,root_path,created_at,updated_at) values(?,?,?,?,?)",
            ("p1", "One", "/one", now, now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into jobs(id,project_id,user_goal,state,risk,created_at,updated_at) values(?,?,?,?,?,?,?)",
                ("j1", "p1", "goal", "DRAFT", "deploy", now, now),
            )

    def test_foreign_key_rejects_orphan_job(self):
        conn = sqlite3.connect(":memory:")
        initialize_schema(conn)
        now = "2026-09-20T00:00:00+00:00"
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "insert into jobs(id,project_id,user_goal,state,created_at,updated_at) values(?,?,?,?,?,?)",
                ("j-orphan", "missing", "goal", "DRAFT", now, now),
            )

    def test_schema_version_mismatch_fails_closed(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("create table meta (key text primary key, value text not null)")
        conn.execute("insert into meta(key,value) values('schema_version','999')")
        conn.commit()
        with self.assertRaises(SchemaVersionError):
            initialize_schema(conn)
        value = conn.execute(
            "select value from meta where key='schema_version'"
        ).fetchone()[0]
        self.assertEqual(value, "999")


class StateStorePersistenceTests(unittest.TestCase):
    def test_project_and_job_survive_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                store.register_project("p1", "Project One", "/fixture/one")
                store.set_active_project("p1")
                store.create_job("j1", "p1", "Fix the failing test", risk="write")
                store.transition_job("j1", JobState.PLANNING)

            with StateStore(db) as reopened:
                project = reopened.get_active_project()
                job = reopened.get_job("j1")
                self.assertEqual(project["id"], "p1")
                self.assertEqual(project["name"], "Project One")
                self.assertEqual(job["project_id"], "p1")
                self.assertEqual(job["state"], "PLANNING")
                self.assertEqual(job["risk"], "write")

    def test_switching_active_project_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                store.register_project("p1", "One", "/fixture/one")
                store.register_project("p2", "Two", "/fixture/two")
                store.set_active_project("p1")
                store.set_active_project("p2")
                self.assertEqual(store.get_active_project()["id"], "p2")
                count = store.connection.execute(
                    "select count(*) from projects where active=1"
                ).fetchone()[0]
                self.assertEqual(count, 1)

    def test_missing_project_does_not_clear_existing_active_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                store.register_project("p1", "One", "/fixture/one")
                store.set_active_project("p1")
                with self.assertRaises(ProjectNotFound):
                    store.set_active_project("missing")
                self.assertEqual(store.get_active_project()["id"], "p1")

    def test_failed_duplicate_root_insert_rolls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                store.register_project("p1", "One", "/fixture/shared")
                with self.assertRaises(sqlite3.IntegrityError):
                    store.register_project("p2", "Two", "/fixture/shared")
                rows = store.connection.execute(
                    "select id from projects order by id"
                ).fetchall()
                self.assertEqual([row[0] for row in rows], ["p1"])

    def test_job_transition_must_follow_canonical_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                store.register_project("p1", "One", "/fixture/one")
                store.create_job("j1", "p1", "goal")
                with self.assertRaises(InvalidJobTransition):
                    store.transition_job("j1", JobState.RUNNING)
                self.assertEqual(store.get_job("j1")["state"], "DRAFT")

    def test_unknown_job_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "xp-next.sqlite3"
            with StateStore(db) as store:
                with self.assertRaises(JobNotFound):
                    store.transition_job("missing", JobState.PLANNING)


if __name__ == "__main__":
    unittest.main()
