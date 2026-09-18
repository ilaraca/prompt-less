"""Identidade e diretórios de uma execução da pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.runtime.atomic_io import UnsafePath, resolve_within

RUNS_DIRNAME = "runs"
ARTIFACTS_DIRNAME = "artifacts"
VALIDATIONS_DIRNAME = "validations"
CHECKPOINTS_DIRNAME = "checkpoints"
# nome único de subdiretório por serviço — igual na run e no espelho outputs/
CONTEXTS_DIRNAME = "contextos"

MAX_ID_LEN = 64
# formato canônico: começa por alfanumérico ou `_` (p/ `_unassigned`), sem
# ponto, barra ou espaço — logo `..`, `a/b` e `C:\x` são rejeitados de saída
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
# `latest` colide com o ponteiro runs/latest.json; `.tmp-` é prefixo interno
RESERVED_IDS = frozenset({"latest", "runs", "tmp"})


class InvalidRunId(ValueError):
    """`run_id` fora do formato canônico."""


class InvalidContextId(ValueError):
    """Identificador de serviço/contexto fora do formato canônico."""


class UnsafeRunPath(UnsafePath):
    """Diretório da run escaparia de `<root>/runs`."""


def _is_canonical(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_ID_LEN
        and bool(_ID_RE.match(value))
    )


def validate_run_id(run_id: object) -> str:
    """Aceita só o formato canônico; qualquer outra coisa é `InvalidRunId`."""
    if not _is_canonical(run_id):
        raise InvalidRunId(
            f"run_id inválido: {run_id!r} — use [A-Za-z0-9_][A-Za-z0-9_-]* "
            f"com até {MAX_ID_LEN} caracteres"
        )
    value = str(run_id)
    if value.lower() in RESERVED_IDS:
        raise InvalidRunId(f"run_id reservado: {value!r}")
    return value


def validate_context_id(context_id: object) -> str:
    if not _is_canonical(context_id):
        raise InvalidContextId(
            f"contexto inválido: {context_id!r} — use [A-Za-z0-9_][A-Za-z0-9_-]* "
            f"com até {MAX_ID_LEN} caracteres"
        )
    return str(context_id)


def context_subdir(base: Path, context_id: str) -> Path:
    """
    Subdiretório canônico de um serviço: `<base>/contextos/<id>`.

    Contrato único usado pela run (`artifacts/`, `validations/`) e pelo espelho
    (`outputs/`). Valida o id e confirma que o resultado não escapa de `base`.
    """
    base = Path(base)
    valid = validate_context_id(context_id)
    return resolve_within(base, base / CONTEXTS_DIRNAME / valid)


def new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:8]
    return f"{timestamp}-{suffix}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    root: Path
    pipeline_version: str
    objective: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", validate_run_id(self.run_id))
        object.__setattr__(self, "root", Path(self.root))
        # falha antes de qualquer escrita se o diretório escapar de <root>/runs
        self._checked_run_dir()

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
            run_id=run_id if run_id is not None else new_run_id(),
            root=root,
            pipeline_version=pipeline_version,
            objective=objective,
        )

    def _checked_run_dir(self) -> Path:
        runs_dir = self.runs_dir
        try:
            return resolve_within(runs_dir, runs_dir / self.run_id)
        except UnsafePath as exc:
            raise UnsafeRunPath(
                f"run_dir de '{self.run_id}' escaparia de {runs_dir}: {exc}"
            ) from exc

    @property
    def runs_dir(self) -> Path:
        return self.root / RUNS_DIRNAME

    @property
    def run_dir(self) -> Path:
        return self._checked_run_dir()

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / ARTIFACTS_DIRNAME

    @property
    def contexts_dir(self) -> Path:
        """Raiz dos artefatos por serviço: `runs/<id>/artifacts/contextos/`."""
        return self.artifacts_dir / CONTEXTS_DIRNAME

    @property
    def validations_dir(self) -> Path:
        return self.run_dir / VALIDATIONS_DIRNAME

    @property
    def checkpoints_dir(self) -> Path:
        return self.run_dir / CHECKPOINTS_DIRNAME

    def context_artifacts_dir(self, context_id: str) -> Path:
        return context_subdir(self.artifacts_dir, context_id)

    def context_validations_dir(self, context_id: str) -> Path:
        return context_subdir(self.validations_dir, context_id)

    @property
    def state_path(self) -> Path:
        return self.run_dir / "state.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"
