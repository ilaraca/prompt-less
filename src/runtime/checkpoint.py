"""Checkpoints versionados por estágio (write-temp + rename)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.atomic_io import atomic_write_json, read_json, sha256_of
from src.runtime.run_context import RunContext
from src.runtime.run_store import RunStore

CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINTS_DIRNAME = "checkpoints"

# eventos da era pré-11, usados só na migração
_LEGACY_COMPLETED = "stage_completed"


def checkpoint_filename(stage_id: str, context_id: str | None = None) -> str:
    if context_id:
        return f"{stage_id}::{context_id}.json"
    return f"{stage_id}.json"


def json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_input_files(inputs_dir: Path | None) -> dict[str, str]:
    if inputs_dir is None or not Path(inputs_dir).is_dir():
        return {}
    root = Path(inputs_dir)
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            hashes[path.relative_to(root).as_posix()] = sha256_of(path)
    return hashes


class CheckpointStore:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.dir = ctx.run_dir / CHECKPOINTS_DIRNAME

    def ensure_dir(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir

    def path_for(self, stage_id: str, context_id: str | None = None) -> Path:
        return self.dir / checkpoint_filename(stage_id, context_id)

    def read(self, stage_id: str, context_id: str | None = None) -> dict[str, Any]:
        data = read_json(self.path_for(stage_id, context_id))
        return data if isinstance(data, dict) else {}

    def write(
        self,
        stage_id: str,
        *,
        status: str,
        context_id: str | None = None,
        input_hashes: dict[str, Any] | None = None,
        attempt: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_dir()
        existing = self.read(stage_id, context_id)
        record = {
            **existing,
            **(extra or {}),
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "stage_id": stage_id,
            "context_id": context_id,
            "status": status,
            "attempt": attempt,
            "input_hashes": input_hashes if input_hashes is not None else existing.get("input_hashes") or {},
            "updated_at": _now(),
        }
        if status == "running" and not existing.get("started_at"):
            record["started_at"] = _now()
        if status in {"completed", "blocked", "failed", "skipped"}:
            record["finished_at"] = _now()
        atomic_write_json(self.path_for(stage_id, context_id), record)
        return record

    def is_completed(self, stage_id: str, context_id: str | None = None) -> bool:
        return self.read(stage_id, context_id).get("status") == "completed"

    def migrate_from_events(self, store: RunStore) -> list[str]:
        """
        Runs antigas (sem `checkpoints/`) ganham checkpoints sintéticos a
        partir de `events.jsonl`. Hash vazio é preenchido na primeira retomada.
        """
        if any(self.dir.glob("*.json")):
            return []
        completed: list[str] = []
        seen: set[str] = set()
        for event in store.events.read_all():
            if event.get("event") != _LEGACY_COMPLETED:
                continue
            stage_id = str(event.get("stage") or "")
            if not stage_id or stage_id in seen:
                continue
            seen.add(stage_id)
            self.write(
                stage_id,
                status="completed",
                extra={"migrated": True, "migrated_from_schema": 0},
            )
            completed.append(stage_id)
        return completed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
