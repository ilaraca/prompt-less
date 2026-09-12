"""Adapter Devin — handoff + coleta de resultado estruturado (sem CLI nos testes)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.executors.base import ExecutionResult


class DevinAdapter:
    id = "devin"

    def __init__(self, *, result_path: Path | None = None) -> None:
        self.result_path = result_path

    def prepare(
        self,
        *,
        run_id: str,
        artifacts_dir: str,
        repository: str,
    ) -> dict[str, Any]:
        art = Path(artifacts_dir)
        return {
            "run_id": run_id,
            "agent": self.id,
            "repository": repository,
            "artifacts_dir": str(art),
            "handoff": {
                "canonical_spec": str(art / "canonical-spec.yaml"),
                "prd": str(next(art.glob("**/PRD.md"), art / "PRD.md")),
                "historia": str(next(art.glob("**/historia.md"), art / "historia.md")),
            },
            "instructions": (
                f"Implemente run_id={run_id} respeitando canonical-spec.yaml. "
                "Mapeie RF/AC/NFR em requirement_traceability. "
                "Não altere arquivos fora do profile da camada."
            ),
        }

    def collect_result(self, payload: dict[str, Any] | None = None) -> ExecutionResult:
        if payload:
            return ExecutionResult.from_dict(payload)
        if self.result_path and self.result_path.is_file():
            data = json.loads(self.result_path.read_text(encoding="utf-8"))
            return ExecutionResult.from_dict(data)
        raise FileNotFoundError(
            "Resultado do Devin ausente: passe payload ou result_path JSON"
        )
