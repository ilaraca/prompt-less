"""Ingestão mínima — só o necessário para o tipo de artefato."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.docs_ingest import load_documents

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "inputs"
TEMPLATES = ROOT / "templates"

ARTIFACT_TEMPLATES = {
    "openapi": TEMPLATES / "openapi.skeleton.yaml",
    "mermaid": TEMPLATES / "mermaid.skeleton.md",
    "historia": TEMPLATES / "historia.skeleton.md",
}


def load_inputs(tipo: str) -> dict[str, Any]:
    if tipo not in ARTIFACT_TEMPLATES:
        raise ValueError(f"tipo inválido: {tipo}")

    figma_path = INPUTS / "figma.json"
    regras_path = INPUTS / "regras.yaml"
    template_path = ARTIFACT_TEMPLATES[tipo]

    figma = json.loads(figma_path.read_text(encoding="utf-8")) if figma_path.exists() else {}
    regras = yaml.safe_load(regras_path.read_text(encoding="utf-8")) if regras_path.exists() else {}
    template = template_path.read_text(encoding="utf-8")
    documents = load_documents(INPUTS)

    return {
        "tipo": tipo,
        "figma": figma,
        "regras": regras,
        "template": template,
        "documents": documents,
    }
