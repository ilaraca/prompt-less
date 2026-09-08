"""Montagem de contexto ≤ budget — estado + RAG comprimido + template."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (ROOT / "prompts" / "system.compact.txt").read_text(encoding="utf-8")


def build_context(
    tipo: str,
    state: dict[str, Any],
    rag: dict[str, Any],
    template: str,
    budget_tokens: int = 2000,
) -> dict[str, Any]:
    # prefixo estável (cacheável) separado do payload dinâmico
    dynamic = {
        "comando": f"Gerar {tipo}",
        "state": state,
        "contexto_comprimido": rag.get("consolidated", ""),
        "template": template,
    }

    # estimativa simples; se estourar budget, corta template markers verbose
    est = (len(SYSTEM) + len(str(dynamic))) // 4
    if est > budget_tokens and len(template) > 400:
        dynamic["template"] = template[:400] + "\n# …template truncado p/ budget"

    return {
        "system": SYSTEM,  # prefixo estável → prompt caching
        "dynamic": dynamic,
        "est_tokens": (len(SYSTEM) + len(str(dynamic))) // 4,
        "rag_stats": {
            "raw": rag.get("est_tokens_raw"),
            "compressed": rag.get("est_tokens_compressed"),
            "docs": (rag.get("documents") or {}).get("docs"),
            "doc_reduction_pct": (rag.get("documents") or {}).get("reduction_pct"),
        },
    }
