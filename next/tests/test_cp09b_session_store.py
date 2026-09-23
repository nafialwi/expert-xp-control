from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from xp_next.state_store import StateStore, StateStoreError


def make_v1_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta(key, value) VALUES('schema_version', '1');

        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_path TEXT NOT NULL UNIQUE,
            source_kind TEXT NOT NULL,
            active INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_goal TEXT NOT NULL,
            state TEXT NOT NULL,
            risk TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        INSERT INTO projects VALUES(
            'p1','Fixture','/tmp/fixture','git',1,'now','now'
        );
        INSERT INTO jobs VALUES(
            'j1','p1','goal','DRAFT','write','now','now'
        );
        """
    )
    connection.commit()
    connection.close()


def create_job(store: StateStore, job_id: str = "j1") -> None:
    project_id = f"p-{job_id}"
    store.register_project(
        project_id,
        f"Project {job_id}",
        f"/tmp/{project_id}",
        source_kind="git",
    )
    store.create_job(job_id, project_id, "goal", risk="write")


class CP09BSessionStoreTests(unittest.TestCase):
    def test_v1_database_upgrades_without_losing_job(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "state.sqlite3"
            make_v1_database(db)

            with StateStore(db) as store:
                self.assertEqual(store.get_job("j1")["user_goal"], "goal")
                session = store.create_work_session("j1", {"phase": "PREPARED"})
                self.assertEqual(session["revision"], 1)
                version = store.connection.execute(
                    "SELECT value FROM meta WHERE key='schema_version'"
                ).fetchone()[0]
                self.assertEqual(version, "2")

    def test_stale_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with StateStore(Path(td) / "state.sqlite3") as store:
                create_job(store)
                session = store.create_work_session("j1", {"phase": "PREPARED"})
                fresh = store.update_work_session(
                    "j1",
                    {"phase": "WORKER_CONFIRMED"},
                    expected_revision=int(session["revision"]),
                )
                self.assertEqual(fresh["revision"], 2)

                with self.assertRaisesRegex(
                    StateStoreError,
                    "work session revision changed; refresh state",
                ):
                    store.update_work_session(
                        "j1",
                        {"phase": "STALE"},
                        expected_revision=1,
                    )

                self.assertEqual(
                    store.get_work_session("j1")["payload"]["phase"],
                    "WORKER_CONFIRMED",
                )

    def test_session_survives_store_restart(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "state.sqlite3"
            with StateStore(db) as store:
                create_job(store)
                store.create_work_session(
                    "j1",
                    {"phase": "PREPARED", "nested": {"ok": True}},
                )

            with StateStore(db) as reopened:
                loaded = reopened.get_work_session("j1")
                self.assertEqual(loaded["revision"], 1)
                self.assertEqual(
                    loaded["payload"],
                    {"nested": {"ok": True}, "phase": "PREPARED"},
                )

    def test_session_payload_is_bounded_to_256000_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            with StateStore(Path(td) / "state.sqlite3") as store:
                create_job(store)
                with self.assertRaisesRegex(
                    StateStoreError,
                    "work session payload exceeds 256000 bytes",
                ):
                    store.create_work_session(
                        "j1",
                        {"large": "x" * 256_100},
                    )

    def test_list_work_sessions_returns_most_recent_first_and_honors_limit(self):
        with tempfile.TemporaryDirectory() as td:
            with StateStore(Path(td) / "state.sqlite3") as store:
                create_job(store, "j1")
                create_job(store, "j2")
                first = store.create_work_session("j1", {"phase": "ONE"})
                store.create_work_session("j2", {"phase": "TWO"})
                store.update_work_session(
                    "j1",
                    {"phase": "ONE-UPDATED"},
                    expected_revision=int(first["revision"]),
                )

                recent = store.list_work_sessions(limit=1)
                self.assertEqual(len(recent), 1)
                self.assertEqual(recent[0]["job_id"], "j1")
                self.assertEqual(recent[0]["payload"]["phase"], "ONE-UPDATED")

                with self.assertRaises(ValueError):
                    store.list_work_sessions(limit=0)


if __name__ == "__main__":
    unittest.main()
