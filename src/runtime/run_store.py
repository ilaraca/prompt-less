"""Persistência de diretório de run, manifest e espelho em outputs/."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.event_store import EventStore
from src.runtime.run_context import RunContext


class RunStore:
    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.events = EventStore(ctx.events_path)

    def bootstrap(self) -> None:
        for d in (
            self.ctx.run_dir,
            self.ctx.artifacts_dir,
            self.ctx.contexts_dir,
            self.ctx.validations_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        self.write_manifest(
            {
                "run_id": self.ctx.run_id,
                "status": "running",
                "started_at": _now(),
                "pipeline_version": self.ctx.pipeline_version,
                "objective": self.ctx.objective,
                "current_stage": "bootstrap",
            }
        )
        self.events.emit("run_started", run_id=self.ctx.run_id, objective=self.ctx.objective)

    def write_manifest(self, data: dict[str, Any]) -> None:
        path = self.ctx.manifest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        existing.update(data)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_provenance(
        self,
        *,
        claims: list[dict[str, Any]],
        discarded: list[dict[str, Any]],
    ) -> Path:
        """Persiste claims e relatório de descarte em validations/."""
        report = {
            "run_id": self.ctx.run_id,
            "claims_count": len(claims),
            "discarded_count": len(discarded),
            "claims": claims,
            "discarded": discarded,
        }
        path = self.ctx.validations_dir / "provenance.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.events.emit(
            "provenance_recorded",
            claims=len(claims),
            discarded=len(discarded),
        )
        return path

    def finish(self, status: str, result: dict[str, Any] | None = None) -> None:
        self.write_manifest(
            {
                "status": status,
                "finished_at": _now(),
                "current_stage": "done" if status == "completed" else status,
                "result_summary": {
                    "split": (result or {}).get("split"),
                    "contexts": (result or {}).get("contexts"),
                    "output": (result or {}).get("output"),
                }
                if result
                else None,
            }
        )
        self.events.emit("run_finished", status=status, run_id=self.ctx.run_id)
        self._write_latest_pointer()

    def mirror_artifacts_to_outputs(self, compat_root: Path) -> None:
        """Cópia compatível runs/<id>/artifacts → <compat_root>/outputs (Devin/scripts)."""
        src = self.ctx.artifacts_dir
        if not src.exists():
            return
        dest = compat_root / "outputs"
        dest.mkdir(parents=True, exist_ok=True)
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    def _write_latest_pointer(self) -> None:
        latest = self.ctx.root / "runs" / "latest.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(
            json.dumps(
                {
                    "run_id": self.ctx.run_id,
                    "run_dir": str(self.ctx.run_dir),
                    "updated_at": _now(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
