"""Identidade e diretórios de uma execução da pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:4]
    return f"{timestamp}-{suffix}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    root: Path
    pipeline_version: str
    objective: str

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        objective: str,
        pipeline_version: str = "1.0",
        run_id: str | None = None,
    ) -> "RunContext":
        return cls(
            run_id=run_id or new_run_id(),
            root=root,
            pipeline_version=pipeline_version,
            objective=objective,
        )

    @property
    def run_dir(self) -> Path:
        return self.root / "runs" / self.run_id

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def contexts_dir(self) -> Path:
        return self.run_dir / "contexts"

    @property
    def validations_dir(self) -> Path:
        return self.run_dir / "validations"

    @property
    def state_path(self) -> Path:
        return self.run_dir / "state.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"
