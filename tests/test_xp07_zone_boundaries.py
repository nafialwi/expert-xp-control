from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("scripts/compat-smoke.py").resolve()


def _load_smoke():
    spec = importlib.util.spec_from_file_location(
        "xp07_a_plus_smoke",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            "cannot load compat-smoke.py"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(
        repo,
        "config",
        "user.email",
        "xp-test@example.invalid",
    )
    _git(
        repo,
        "config",
        "user.name",
        "XP Test",
    )
    (repo / ".gitignore").write_text(
        "dist/\ncache/\n.xp/local-cache/\n",
        encoding="utf-8",
    )
    (repo / "src.txt").write_text(
        "SOURCE\n",
        encoding="utf-8",
    )
    xp = repo / ".xp"
    xp.mkdir()
    (xp / "project.json").write_text(
        json.dumps(
            {
                "profile_version": 1,
                "project_id": "zone-fixture",
                "name": "Zone Fixture",
                "runtimes": [],
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    local_cache = xp / "local-cache"
    local_cache.mkdir()
    (local_cache / "probe.txt").write_text(
        "CACHE0\n",
        encoding="utf-8",
    )
    _git(
        repo,
        "add",
        ".gitignore",
        "src.txt",
        ".xp/project.json",
    )
    _git(
        repo,
        "commit",
        "-m",
        "baseline",
    )
    return repo


class XP07APlusBoundaryTests(unittest.TestCase):
    def test_zone2_allows_only_git_ignored_artifact_changes(self):
        smoke = _load_smoke()

        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            before = smoke.zone2_canonical_snapshot(
                repo
            )

            dist = repo / "dist"
            dist.mkdir()
            (dist / "bundle.js").write_text(
                "ignored build output\n",
                encoding="utf-8",
            )

            after = smoke.zone2_canonical_snapshot(
                repo
            )
            report = smoke.assert_zone2_unchanged(
                before,
                after,
                repo,
                "ignored artifact fixture",
            )

            self.assertTrue(
                report[
                    "canonical_boundary_unchanged"
                ]
            )
            self.assertIn(
                "dist/bundle.js",
                report["ignored_changes"],
            )
            self.assertEqual(
                report[
                    "harness_added_exclusions"
                ],
                [],
            )

    def test_zone2_rejects_tracked_source_mutation(self):
        smoke = _load_smoke()

        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            before = smoke.zone2_canonical_snapshot(
                repo
            )
            (repo / "src.txt").write_text(
                "MUTATED\n",
                encoding="utf-8",
            )
            after = smoke.zone2_canonical_snapshot(
                repo
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "ZONE2 VIOLATION",
            ):
                smoke.assert_zone2_unchanged(
                    before,
                    after,
                    repo,
                    "tracked mutation fixture",
                )

    def test_zone2_explicitly_protects_ignored_xp_content(self):
        smoke = _load_smoke()

        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            before = smoke.zone2_canonical_snapshot(
                repo
            )
            probe = (
                repo
                / ".xp"
                / "local-cache"
                / "probe.txt"
            )
            probe.write_text(
                "CACHE1\n",
                encoding="utf-8",
            )
            after = smoke.zone2_canonical_snapshot(
                repo
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "ZONE2 VIOLATION",
            ):
                smoke.assert_zone2_unchanged(
                    before,
                    after,
                    repo,
                    "ignored xp mutation fixture",
                )

    def test_zone1_full_tree_detects_git_and_ignored_byte_changes(self):
        smoke = _load_smoke()

        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            before = smoke.full_tree_byte_snapshot(
                repo
            )

            ignored = repo / "cache"
            ignored.mkdir()
            (ignored / "probe.bin").write_bytes(
                b"ignored"
            )
            git_probe = (
                repo
                / ".git"
                / "zone1-probe"
            )
            git_probe.write_bytes(
                b"git-byte-change"
            )

            after = smoke.full_tree_byte_snapshot(
                repo
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "ZONE1 VIOLATION",
            ):
                smoke.assert_zone1_unchanged(
                    before,
                    after,
                    "zone1 fixture",
                )

    def test_zone1_command_guard_blocks_subprocess_inside_original(self):
        smoke = _load_smoke()

        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td))
            smoke.install_original_repo_guard(
                repo
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "ZONE1 VIOLATION",
            ):
                smoke.run(
                    ["git", "status"],
                    cwd=repo,
                )


if __name__ == "__main__":
    unittest.main()
