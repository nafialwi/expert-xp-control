from __future__ import annotations

import sys
import threading

from . import __version__

PRODUCT_NAME = "EXPERT WORKSTATION"
ENGINE_NAME = "XP"
BYLINE = "by Rahmawan"


def clear_screen() -> None:
    """Clear an interactive terminal without polluting redirected test/log output."""
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)


def header() -> None:
    print("╔══════════════════════════════════════╗")
    print("║          EXPERT WORKSTATION          ║")
    print("║" + f"XP v{__version__}".center(38) + "║")
    print("╚══════════════════════════════════════╝")
    print("              by Rahmawan")
    print()


def wait_for_enter() -> None:
    """Pause only for a real human terminal; automation/tests continue immediately."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            input("\nTekan Enter untuk kembali...")
        except (EOFError, KeyboardInterrupt):
            print()


def human_path(path) -> str:
    """Prefer a short, human-facing path for artifacts under Downloads."""
    text = str(path)
    marker = "/storage/downloads/"
    if marker in text:
        return "Download/" + text.split(marker, 1)[1]
    return getattr(path, "name", text)


SPINNER_FRAMES = ("-", "\\", "|", "/")


class Spinner:
    """Small terminal spinner so long silent gates never look like a hang."""

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread = None

    def _spin(self):
        index = 0
        while not self._stop.is_set():
            frame = SPINNER_FRAMES[index % len(SPINNER_FRAMES)]
            sys.stdout.write(f"\r{frame} {self.label} ")
            sys.stdout.flush()
            index += 1
            self._stop.wait(0.15)

    def __enter__(self):
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc_info):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)
            sys.stdout.write("\r" + " " * (len(self.label) + 4) + "\r")
            sys.stdout.flush()
        return False
