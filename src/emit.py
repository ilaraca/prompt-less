"""Emissão do artefato — um arquivo, sem prosa."""
from __future__ import annotations

from pathlib import Path

from src.runtime.atomic_io import atomic_write_text
from src.runtime.run_context import context_subdir

ROOT = Path(__file__).resolve().parents[1]

# arquivos na raiz de outputs/ (legado / single-context)
OUTPUTS = {
    "openapi": "openapi.yaml",
    "mermaid": "sequence.mmd",
    "historia": "historia.md",
    "prd": "PRD.md",
}


def emit(
    tipo: str,
    content: str,
    *,
    context: str | None = None,
    root: Path | None = None,
    subdir: str = "outputs",
) -> Path:
    name = OUTPUTS[tipo]
    base = root or ROOT
    if context:
        path = context_subdir(base / subdir, context) / name
    else:
        path = base / subdir / name
    atomic_write_text(path, content)
    return path
