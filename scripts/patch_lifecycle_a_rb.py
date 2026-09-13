#!/usr/bin/env python3
from __future__ import annotations

import ast
import copy
import textwrap
from pathlib import Path

MISMATCH_TOKEN = "candidate mismatch"


def _class_node(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "EngineLifecycle":
            return node
    raise RuntimeError("EngineLifecycle class not found")


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise RuntimeError(f"EngineLifecycle.{name} not found")


def _contains_mismatch(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if MISMATCH_TOKEN in child.value:
                return True
    return False


def _candidate_version_assignment(node: ast.Assign) -> bool:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return False
    if node.targets[0].id != "candidate":
        return False
    call = node.value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr == "candidate_version"
    )


class _PrivateSwitchTransformer(ast.NodeTransformer):
    def __init__(self, version_name: str):
        self.version_name = version_name
        self.removed_guard = False

    def visit_If(self, node: ast.If):
        if _contains_mismatch(node):
            self.removed_guard = True
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        node = self.generic_visit(node)
        if isinstance(node, ast.Assign) and _candidate_version_assignment(node):
            node.value = ast.Name(id=self.version_name, ctx=ast.Load())
        return node


def _ensure_imports(text: str) -> str:
    needed = []
    if not any(line.strip() == "import json" for line in text.splitlines()):
        needed.append("import json")
    if "from datetime import datetime, timezone" not in text:
        needed.append("from datetime import datetime, timezone")
    if not needed:
        return text

    lines = text.splitlines(keepends=True)
    insert = 0
    if lines and lines[0].startswith("from __future__ import"):
        insert = 1
        while insert < len(lines) and not lines[insert].strip():
            insert += 1
    lines.insert(insert, "\n".join(needed) + "\n")
    return "".join(lines)


def _canonical_public_method(version_name: str) -> str:
    return (
        "    def activate_candidate(self, " + version_name + ": str):\n"
        "        candidate = self.candidate_version()\n"
        "        if candidate != " + version_name + ":\n"
        "            raise ValueError(\n"
        "                f\"candidate mismatch: expected {candidate or '-'}, "
        "got {" + version_name + " or '-'}\"\n"
        "            )\n"
        "        return self._switch_active_version(" + version_name + ")\n"
    )


def _rollback_methods() -> str:
    return '''
    def _record_rollback(self, version: str, *, reason: str):
        journal = self.paths.root / "engine-rollback-journal.jsonl"
        event = {
            "version": str(version),
            "reason": str(reason or "manual rollback"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        existing = journal.read_text(encoding="utf-8") if journal.is_file() else ""
        tmp = journal.with_name(journal.name + f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(existing)
            if existing and not existing.endswith("\\n"):
                handle.write("\\n")
            handle.write(json.dumps(event, sort_keys=True) + "\\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, journal)
        return event

    def rollback_to_previous(self, *, reason: str = "manual rollback"):
        previous = self.previous_version()
        if not previous:
            raise RuntimeError("previous engine version is not available")
        target = self.paths.versions / previous
        if not target.is_dir():
            raise FileNotFoundError(
                f"previous installed engine directory not found: {previous}"
            )
        departed = self.active_version()
        if not departed:
            raise RuntimeError("active engine version is not available")

        result = self._switch_active_version(previous)

        if self.candidate_version() is not None:
            raise RuntimeError("candidate marker was not cleared after rollback")
        self._record_rollback(departed, reason=reason)
        return result
'''


def patch(path: Path) -> None:
    path = Path(path)
    text = _ensure_imports(path.read_text(encoding="utf-8"))
    tree = ast.parse(text)
    cls = _class_node(tree)

    existing = {
        node.name
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
    }
    if "_switch_active_version" in existing or "rollback_to_previous" in existing:
        raise RuntimeError(
            "A-RB lifecycle methods already present; refusing ambiguous patch"
        )

    activate = _method(cls, "activate_candidate")
    if not _contains_mismatch(activate):
        raise RuntimeError(
            "activate_candidate candidate-mismatch guard not found"
        )
    if len(activate.args.args) < 2:
        raise RuntimeError(
            "activate_candidate version parameter not found"
        )
    version_name = activate.args.args[1].arg

    private = copy.deepcopy(activate)
    private.name = "_switch_active_version"
    transformer = _PrivateSwitchTransformer(version_name)
    private = transformer.visit(private)
    ast.fix_missing_locations(private)

    if not transformer.removed_guard:
        raise RuntimeError(
            "private switch transform did not remove candidate guard"
        )

    private_src = textwrap.indent(
        ast.unparse(private),
        "    ",
    ) + "\n\n"
    public_src = _canonical_public_method(version_name) + "\n"
    rollback_src = _rollback_methods() + "\n"

    lines = text.splitlines(keepends=True)
    start = activate.lineno - 1
    end = activate.end_lineno
    lines[start:end] = [
        private_src,
        public_src,
        rollback_src,
    ]
    patched = "".join(lines)

    parsed = ast.parse(patched)
    cls2 = _class_node(parsed)
    private2 = _method(cls2, "_switch_active_version")
    public2 = _method(cls2, "activate_candidate")
    rollback2 = _method(cls2, "rollback_to_previous")

    if _contains_mismatch(private2):
        raise RuntimeError(
            "candidate guard leaked into private switch primitive"
        )
    if not _contains_mismatch(public2):
        raise RuntimeError(
            "public activate_candidate lost candidate guard"
        )

    public_text = ast.get_source_segment(
        patched,
        public2,
    ) or ""
    rollback_text = ast.get_source_segment(
        patched,
        rollback2,
    ) or ""

    if "self._switch_active_version" not in public_text:
        raise RuntimeError(
            "activate_candidate does not use shared switch primitive"
        )
    if "self._switch_active_version" not in rollback_text:
        raise RuntimeError(
            "rollback_to_previous does not use shared switch primitive"
        )
    if "self.activate_candidate" in rollback_text:
        raise RuntimeError(
            "rollback still delegates through candidate activation"
        )

    path.write_text(
        patched,
        encoding="utf-8",
    )


def _self_test() -> None:
    import tempfile

    sample = '''
from __future__ import annotations
import os
from pathlib import Path

class EngineLifecycle:
    def __init__(self, paths):
        self.paths = paths

    def candidate_version(self):
        return "2.1.0-rc1"

    def active_version(self):
        return "2.0.0-rc18.3"

    def previous_version(self):
        return "2.0.0-rc18.3"

    def _atomic_write(self, path, value):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(value + "\\n")
        os.replace(tmp, path)

    def activate_candidate(self, version: str):
        candidate = self.candidate_version()
        if candidate != version:
            raise ValueError(
                f"candidate mismatch: expected {candidate or '-'}, got {version or '-'}"
            )
        target = self.paths.versions / version
        if not target.is_dir():
            raise FileNotFoundError(version)
        current = self.active_version()
        self._atomic_write(
            self.paths.root / "previous-version",
            current,
        )
        self._atomic_write(
            self.paths.root / "active-version",
            version,
        )
        return {"activated": version}
'''

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "engine_lifecycle.py"
        path.write_text(
            sample,
            encoding="utf-8",
        )
        patch(path)
        result = path.read_text(
            encoding="utf-8",
        )
        ast.parse(result)
        if "def _switch_active_version" not in result:
            raise RuntimeError(
                "self-test: switch primitive missing"
            )
        if "def rollback_to_previous" not in result:
            raise RuntimeError(
                "self-test: rollback missing"
            )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        print(
            "A-RB PATCHER SELF-TEST: PASS"
        )
        return 0

    if not args.path:
        parser.error(
            "path is required unless --self-test is used"
        )

    patch(
        Path(args.path)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
