"""Emissão do artefato — um arquivo, sem prosa."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = {
    "openapi": ROOT / "outputs" / "openapi.yaml",
    "mermaid": ROOT / "outputs" / "sequence.mmd",
    "historia": ROOT / "outputs" / "historia.md",
    "prd": ROOT / "outputs" / "PRD.md",
}


def emit(tipo: str, content: str) -> Path:
    path = OUTPUTS[tipo]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
