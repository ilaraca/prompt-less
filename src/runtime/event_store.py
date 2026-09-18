"""Event store append-only por execução."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.integrity import GENESIS_HASH, event_hash


class EventStore:
    def __init__(self, path: Path) -> None:
        # nada é criado aqui: o diretório da run só nasce no bootstrap, que
        # depende de `mkdir` exclusivo para detectar colisão de run_id
        self.path = Path(path)
        self._tip: str | None = None

    def emit(self, event: str, **details: Any) -> dict[str, Any]:
        record = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "prev_hash": self.tip,
            **details,
        }
        record["hash"] = event_hash(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._tip = record["hash"]
        return record

    @property
    def tip(self) -> str:
        if self._tip is not None:
            return self._tip
        rows = self.read_all()
        if not rows:
            self._tip = GENESIS_HASH
            return self._tip
        last = rows[-1]
        self._tip = str(last.get("hash") or event_hash(last))
        return self._tip

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
