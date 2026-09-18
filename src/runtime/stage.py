"""Protocolo de estágio, contexto de execução e registry de handlers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from src.runtime.atomic_io import UnsafePath, atomic_write_json, atomic_write_text, resolve_within
from src.runtime.run_context import RunContext
from src.runtime.run_store import RunStore

Handler = Callable[["StageContext"], Any]


class StageError(RuntimeError):
    """Falha de um estágio (após retries, se houver)."""


class StageTimeout(StageError):
    """O estágio excedeu `timeout_s`."""


class HashMismatch(StageError):
    """Retomada recusada: hash das entradas não bate com o checkpoint."""


class GraphError(ValueError):
    """Grafo de estágios inválido (ciclo, handler ausente, id duplicado)."""


class Stage(Protocol):
    """Contrato mínimo de um estágio executável."""

    id: str

    def run(self, ctx: "StageContext") -> Any: ...


@dataclass
class StageResult:
    stage_id: str
    status: str  # completed | skipped | blocked | failed
    attempt: int = 1
    details: dict[str, Any] = field(default_factory=dict)
    context_id: str | None = None


@dataclass
class StageContext:
    """Bag da execução de um estágio — escritas só dentro de `run_dir`."""

    stage_id: str
    run_ctx: RunContext
    store: RunStore
    cfg: dict[str, Any]
    payload: dict[str, Any]
    context_id: str | None = None
    attempt: int = 1

    def slot(self) -> dict[str, Any]:
        """Estado por contexto de serviço (`""` = run sem split)."""
        per = self.payload.setdefault("per_context", {})
        key = self.context_id if self.context_id is not None else ""
        return per.setdefault(key, {})

    def confine(self, path: Path | str) -> Path:
        """Resolve `path` e recusa qualquer destino fora do diretório da run."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.run_ctx.run_dir / candidate
        try:
            return resolve_within(self.run_ctx.run_dir, candidate)
        except UnsafePath as exc:
            raise UnsafePath(
                f"handler '{self.stage_id}' não pode escrever fora de "
                f"{self.run_ctx.run_dir}: {exc}"
            ) from exc

    def write_json(self, path: Path | str, data: Any) -> Path:
        return atomic_write_json(self.confine(path), data)

    def write_text(self, path: Path | str, text: str) -> Path:
        return atomic_write_text(self.confine(path), text)


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, handler: Handler | None = None):
        """Uso: `registry.register("ingest", fn)` ou `@registry.register("ingest")`."""
        if handler is not None:
            self._handlers[name] = handler
            return handler

        def decorator(fn: Handler) -> Handler:
            self._handlers[name] = fn
            return fn

        return decorator

    def get(self, name: str) -> Handler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise GraphError(f"handler desconhecido: {name!r}") from exc

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._handlers

    def names(self) -> frozenset:
        return frozenset(self._handlers)
