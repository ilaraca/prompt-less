"""Contrato de execução e adapter base."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class ExecutionResult:
    run_id: str
    agent: str
    repository: str
    base_commit: str | None = None
    result_commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    commands_executed: list[str] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    requirement_traceability: dict[str, list[str]] = field(default_factory=dict)
    layer: str | None = None
    approved: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionResult":
        return cls(
            run_id=str(data.get("run_id") or ""),
            agent=str(data.get("agent") or "unknown"),
            repository=str(data.get("repository") or ""),
            base_commit=data.get("base_commit"),
            result_commit=data.get("result_commit"),
            changed_files=list(data.get("changed_files") or []),
            commands_executed=list(data.get("commands_executed") or []),
            tests=list(data.get("tests") or []),
            unresolved_items=list(data.get("unresolved_items") or []),
            requirement_traceability=dict(data.get("requirement_traceability") or {}),
            layer=data.get("layer"),
            approved=data.get("approved"),
        )


class ExecutorAdapter(Protocol):
    id: str

    def prepare(self, *, run_id: str, artifacts_dir: str, repository: str) -> dict[str, Any]:
        """Prepara handoff (docs/prompt-less, prompt)."""

    def collect_result(self, payload: dict[str, Any] | None = None) -> ExecutionResult:
        """Coleta resultado estruturado (arquivo, API ou stub)."""
