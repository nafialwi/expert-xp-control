from __future__ import annotations
import argparse
import json
from .service import doctor, status, version

def _print(data: dict[str, object]) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xp-next")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    sub.add_parser("status")
    sub.add_parser("doctor")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        _print(version())
        return 0
    if args.command == "status":
        _print(status())
        return 0
    if args.command == "doctor":
        _print(doctor())
        return 0
    raise AssertionError("unreachable")

if __name__ == "__main__":
    raise SystemExit(main())
