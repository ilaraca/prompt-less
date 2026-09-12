"""Emissão do artefato — um arquivo, sem prosa."""
from __future__ import annotations

from pathlib import Path

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
        path = base / subdir / "contextos" / context / name
    else:
        path = base / subdir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
