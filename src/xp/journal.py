import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def before(self, operation: str, metadata: dict[str, Any]) -> str:
        entry_id = uuid.uuid4().hex
        self._append(
            {
                "type": "BEFORE",
                "entry_id": entry_id,
                "operation": operation,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return entry_id

    def after(self, entry_id: str, result: str, metadata: dict[str, Any]) -> None:
        self._append(
            {
                "type": "AFTER",
                "entry_id": entry_id,
                "result": result,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def interrupted_operation(self) -> dict[str, Any] | None:
        open_entries: dict[str, dict[str, Any]] = {}
        for record in self._records():
            if record.get("type") == "BEFORE":
                open_entries[record["entry_id"]] = record
            elif record.get("type") == "AFTER":
                open_entries.pop(record.get("entry_id"), None)
        if not open_entries:
            return None
        return list(open_entries.values())[-1]
