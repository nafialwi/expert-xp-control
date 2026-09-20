from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from xp_next.apply_control import (
    ApplyGuardError,
    ApplyStatus,
    apply_reviewed_sandbox,
    discard_reviewed_sandbox,
    rollback_recovery,
)
from xp_next.isolated_workspace import (
    prepare_isolated_workspace,
    workspace_changed_paths,
)
from xp_next.sandbox_review import VerifierSpec, build_review_bundle


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_source(root: Path) -> str:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "app.txt").write_text("SAFE\n", encoding="utf-8")
    (root / "delete-me.txt").write_text("DELETE_ME\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return git(root, "rev-parse", "HEAD")


def verifier(name: str = "content-check") -> VerifierSpec:
    return VerifierSpec(
        name=name,
        argv=(
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "assert Path('app.txt').read_text().splitlines() == ['CHANGED']; "
                "assert Path('new.txt').read_text() == 'NEW\\n'; "
                "assert not Path('delete-me.txt').exists()"
            ),
        ),
    )


def prepare_case(base: Path):
    source = base / "source"
    expected_head = init_source(source)
    isolated = prepare_isolated_workspace(
        source,
        base / "sandboxes",
        job_id="job-1",
    )
    (isolated.project / "app.txt").write_text("CHANGED\n", encoding="utf-8")
    (isolated.project / "new.txt").write_text("NEW\n", encoding="utf-8")
    (isolated.project / "delete-me.txt").unlink()
    spec = verifier()
    bundle = build_review_bundle(isolated.project, verifier_specs=(spec,))
    return source, expected_head, isolated, spec, bundle


class ApplyControlTests(unittest.TestCase):
    def test_apply_pass_creates_recovery_and_does_not_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            self.assertEqual(bundle.status.value, "PASS")
            before_remote = git(source, "remote")

            result = apply_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(spec,),
                expected_original_head=head,
                recovery_parent=base / "recovery",
                recovery_id="rp-1",
            )

            self.assertEqual(result.status, ApplyStatus.APPLIED)
            self.assertTrue(result.apply_performed)
            self.assertFalse(result.rollback_performed)
            self.assertEqual(git(source, "rev-parse", "HEAD"), head)
            self.assertEqual(git(source, "remote"), before_remote)
            self.assertEqual(
                workspace_changed_paths(source),
                ("app.txt", "delete-me.txt", "new.txt"),
            )
            self.assertEqual((source / "app.txt").read_text(), "CHANGED\n")
            self.assertEqual((source / "new.txt").read_text(), "NEW\n")
            self.assertFalse((source / "delete-me.txt").exists())
            manifest = Path(result.recovery_ref) / "manifest.json"
            self.assertTrue(manifest.is_file())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["original_head"], head)
            self.assertEqual(data["state"], "APPLIED")

    def test_post_apply_verifier_failure_rolls_back_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, _, _ = prepare_case(base)
            path_sensitive = VerifierSpec(
                name="sandbox-only",
                argv=(
                    "python",
                    "-c",
                    (
                        "from pathlib import Path; "
                        "assert Path.cwd().name == 'project'; "
                        "assert Path('app.txt').read_text().splitlines() == ['CHANGED']"
                    ),
                ),
            )
            bundle = build_review_bundle(
                isolated.project,
                verifier_specs=(path_sensitive,),
            )
            self.assertEqual(bundle.status.value, "PASS")

            result = apply_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(path_sensitive,),
                expected_original_head=head,
                recovery_parent=base / "recovery",
                recovery_id="rp-fail",
            )

            self.assertEqual(result.status, ApplyStatus.ROLLED_BACK)
            self.assertTrue(result.apply_performed)
            self.assertTrue(result.rollback_performed)
            self.assertEqual(workspace_changed_paths(source), ())
            self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            self.assertEqual((source / "delete-me.txt").read_text(), "DELETE_ME\n")
            self.assertFalse((source / "new.txt").exists())

    def test_post_apply_verifier_side_effect_is_removed_by_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, _, _ = prepare_case(base)
            mutates_original_only = VerifierSpec(
                name="side-effect-on-original",
                argv=(
                    "python",
                    "-c",
                    (
                        "from pathlib import Path; "
                        "p=Path.cwd(); "
                        "(p/'verifier-side-effect.txt').write_text('x') if p.name == 'source' else None; "
                        "assert Path('app.txt').read_text().splitlines() == ['CHANGED']"
                    ),
                ),
            )
            bundle = build_review_bundle(
                isolated.project,
                verifier_specs=(mutates_original_only,),
            )
            self.assertEqual(bundle.status.value, "PASS")

            result = apply_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(mutates_original_only,),
                expected_original_head=head,
                recovery_parent=base / "recovery",
                recovery_id="rp-side-effect",
            )

            self.assertEqual(result.status, ApplyStatus.ROLLED_BACK)
            self.assertTrue(result.rollback_performed)
            self.assertFalse((source / "verifier-side-effect.txt").exists())
            self.assertEqual(workspace_changed_paths(source), ())
            self.assertEqual((source / "app.txt").read_text(), "SAFE\n")

    def test_stale_dirty_original_is_rejected_before_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            (source / "app.txt").write_text("USER_EDIT\n", encoding="utf-8")

            with self.assertRaises(ApplyGuardError):
                apply_reviewed_sandbox(
                    original_root=source,
                    sandbox_root=isolated.project,
                    approved_review=bundle,
                    verifier_specs=(spec,),
                    expected_original_head=head,
                    recovery_parent=base / "recovery",
                    recovery_id="rp-dirty",
                )

            self.assertFalse((base / "recovery" / "rp-dirty").exists())
            self.assertEqual((source / "app.txt").read_text(), "USER_EDIT\n")

    def test_changed_original_head_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            (source / "extra.txt").write_text("later\n", encoding="utf-8")
            git(source, "add", ".")
            git(source, "commit", "-qm", "later")

            with self.assertRaises(ApplyGuardError):
                apply_reviewed_sandbox(
                    original_root=source,
                    sandbox_root=isolated.project,
                    approved_review=bundle,
                    verifier_specs=(spec,),
                    expected_original_head=head,
                    recovery_parent=base / "recovery",
                    recovery_id="rp-head",
                )

    def test_stale_sandbox_after_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            (isolated.project / "new.txt").write_text("MUTATED_AFTER_REVIEW\n", encoding="utf-8")

            with self.assertRaises(ApplyGuardError):
                apply_reviewed_sandbox(
                    original_root=source,
                    sandbox_root=isolated.project,
                    approved_review=bundle,
                    verifier_specs=(spec,),
                    expected_original_head=head,
                    recovery_parent=base / "recovery",
                    recovery_id="rp-stale",
                )

            self.assertEqual(workspace_changed_paths(source), ())

    def test_truncated_review_cannot_be_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            head = init_source(source)
            isolated = prepare_isolated_workspace(
                source,
                base / "sandboxes",
                job_id="job-large",
            )
            (isolated.project / "large.txt").write_text("A" * 8000 + "\n")
            spec = VerifierSpec(
                name="large-check",
                argv=("python", "-c", "from pathlib import Path; assert Path('large.txt').exists()"),
            )
            bundle = build_review_bundle(
                isolated.project,
                verifier_specs=(spec,),
                max_diff_chars=500,
            )
            self.assertTrue(bundle.diff_truncated)
            self.assertEqual(bundle.status.value, "PASS")

            with self.assertRaises(ApplyGuardError):
                apply_reviewed_sandbox(
                    original_root=source,
                    sandbox_root=isolated.project,
                    approved_review=bundle,
                    verifier_specs=(spec,),
                    expected_original_head=head,
                    recovery_parent=base / "recovery",
                    recovery_id="rp-large",
                    max_diff_chars=500,
                )

    def test_discard_leaves_original_untouched_and_creates_no_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            result = discard_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(spec,),
                expected_original_head=head,
            )
            self.assertEqual(result.status, ApplyStatus.DISCARDED)
            self.assertFalse(result.apply_performed)
            self.assertFalse(result.rollback_performed)
            self.assertIsNone(result.recovery_ref)
            self.assertEqual(workspace_changed_paths(source), ())
            self.assertEqual((source / "app.txt").read_text(), "SAFE\n")

    def test_manual_rollback_restores_successful_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            applied = apply_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(spec,),
                expected_original_head=head,
                recovery_parent=base / "recovery",
                recovery_id="rp-manual",
            )
            rolled = rollback_recovery(
                original_root=source,
                recovery_ref=Path(applied.recovery_ref),
            )
            self.assertEqual(rolled.status, ApplyStatus.ROLLED_BACK)
            self.assertEqual(workspace_changed_paths(source), ())
            self.assertEqual((source / "app.txt").read_text(), "SAFE\n")
            self.assertEqual((source / "delete-me.txt").read_text(), "DELETE_ME\n")
            self.assertFalse((source / "new.txt").exists())

    def test_manual_rollback_refuses_user_change_after_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source, head, isolated, spec, bundle = prepare_case(base)
            applied = apply_reviewed_sandbox(
                original_root=source,
                sandbox_root=isolated.project,
                approved_review=bundle,
                verifier_specs=(spec,),
                expected_original_head=head,
                recovery_parent=base / "recovery",
                recovery_id="rp-stale-rollback",
            )
            (source / "app.txt").write_text("USER_AFTER_APPLY\n", encoding="utf-8")

            with self.assertRaises(ApplyGuardError):
                rollback_recovery(
                    original_root=source,
                    recovery_ref=Path(applied.recovery_ref),
                )

            self.assertEqual((source / "app.txt").read_text(), "USER_AFTER_APPLY\n")


if __name__ == "__main__":
    unittest.main()
