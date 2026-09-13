#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xp.schema import schema_for


BEGIN = "<!-- XP_SCHEMA_CONTRACT_BEGIN -->"
END = "<!-- XP_SCHEMA_CONTRACT_END -->"


def canonical_contract() -> dict:
    return {
        name: schema_for(name)
        for name in (
            "work",
            "remediation",
            "project-profile",
        )
    }


def render_block() -> str:
    payload = json.dumps(
        canonical_contract(),
        indent=2,
        sort_keys=True,
    )
    return f"{BEGIN}\n{payload}\n{END}"


def update_handshake(path: Path) -> None:
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.is_file() else "# XP External AI Handshake\n"
    block = render_block()

    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END, start) + len(END)
        text = text[:start].rstrip() + "\n\n" + block + "\n" + text[end:].lstrip()
    else:
        text = text.rstrip() + "\n\n## Canonical XP schema contract\n\n" + block + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--handshake",
        default="docs/handshake.md",
    )
    args = parser.parse_args()
    update_handshake(Path(args.handshake))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
