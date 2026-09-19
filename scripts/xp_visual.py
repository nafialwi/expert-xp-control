#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import threading
import urllib.request
from pathlib import Path

from xp.visual_server import make_server
from xp.visual_workstation import SnapshotStore, VisualWorkstationSnapshot


def default_state_path() -> Path:
    return (
        Path.home()
        / ".expert-workstation"
        / "state"
        / "visual-workstation.json"
    )


def static_root() -> Path:
    return Path(__file__).resolve().parents[1] / "web" / "xp_visual"


def self_test() -> int:
    with __import__("tempfile").TemporaryDirectory(
        prefix="xp-af10-pwa-"
    ) as td:
        state = Path(td) / "state.json"
        SnapshotStore(state).write(
            VisualWorkstationSnapshot(
                project="AF10 Self Test",
                checkpoint="SELF-TEST",
                recovery_status="READY",
                mode="OFFLINE",
                provider="local",
                model="self-test",
                cost_state="FREE",
                worker="NONE",
                permission="READ_ONLY",
                approval="NOT_REQUIRED",
                verification="PASS",
                rollback="NOT_PERFORMED",
                final_status="COMPLETED",
                live=False,
                activities=(),
            )
        )
        server = make_server(
            host="127.0.0.1",
            port=0,
            static_root=static_root(),
            state_path=state,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()
        host, port = server.server_address[:2]
        base = f"http://{host}:{port}"
        try:
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                html = response.read().decode("utf-8")
                assert response.status == 200
                assert "Expert XP" in html
                assert "Activity Trail" in html

            with urllib.request.urlopen(
                base + "/api/status",
                timeout=5,
            ) as response:
                data = json.loads(
                    response.read().decode("utf-8")
                )
                assert data["project"] == "AF10 Self Test"
                assert data["mode"] == "OFFLINE"
                assert data["verification"] == "PASS"

            with urllib.request.urlopen(
                base + "/manifest.webmanifest",
                timeout=5,
            ) as response:
                manifest = json.loads(
                    response.read().decode("utf-8")
                )
                assert manifest["display"] == "standalone"

            with urllib.request.urlopen(
                base + "/sw.js",
                timeout=5,
            ) as response:
                sw = response.read().decode("utf-8")
                assert "cache.addAll" in sw

            print("AF10_PWA_HTTP_SMOKE=PASS")
            print("AF10_STATUS_API=PASS")
            print("AF10_MANIFEST=PASS")
            print("AF10_SERVICE_WORKER=PASS")
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expert XP local visual workstation"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--state",
        type=Path,
        default=default_state_path(),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    server = make_server(
        host=args.host,
        port=args.port,
        static_root=static_root(),
        state_path=args.state,
    )
    print(
        f"Expert XP Visual: http://{args.host}:{args.port}"
    )
    print(
        "Local-only UI. Ctrl+C returns to the terminal."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
