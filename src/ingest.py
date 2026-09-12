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
    "prd": TEMPLATES / "prd.skeleton.md",
}


def load_inputs(tipo: str, inputs_dir: Path | None = None) -> dict[str, Any]:
    if tipo not in ARTIFACT_TEMPLATES:
        raise ValueError(f"tipo inválido: {tipo}")

    base = inputs_dir or INPUTS
    figma_path = base / "figma.json"
    regras_path = base / "regras.yaml"
    engenharia_path = base / "engenharia.yaml"
    template_path = ARTIFACT_TEMPLATES[tipo]

    figma = json.loads(figma_path.read_text(encoding="utf-8")) if figma_path.exists() else {}
    regras = yaml.safe_load(regras_path.read_text(encoding="utf-8")) if regras_path.exists() else {}
    engenharia = (
        yaml.safe_load(engenharia_path.read_text(encoding="utf-8")) if engenharia_path.exists() else {}
    ) or {}
    template = template_path.read_text(encoding="utf-8")
    documents = load_documents(base)

    return {
        "tipo": tipo,
        "figma": figma,
        "regras": regras,
        "engenharia": engenharia,
        "template": template,
        "documents": documents,
    }
