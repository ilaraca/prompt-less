"""Montagem de contexto ≤ budget — estado + RAG comprimido + template."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tokenizer import HEURISTIC_CHARS_PER_TOKEN, TokenEstimate, estimate

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (ROOT / "prompts" / "system.compact.txt").read_text(encoding="utf-8")


def _payload(system: str, dynamic: dict[str, Any]) -> str:
    return system + str(dynamic)


def _count(system: str, dynamic: dict[str, Any]) -> TokenEstimate:
    return estimate(_payload(system, dynamic))


def _fit_to_budget(
    dynamic: dict[str, Any],
    budget_tokens: int,
) -> TokenEstimate:
    """Corta template e consolidado até caber no teto (ou até não haver mais corte)."""
    est = _count(SYSTEM, dynamic)
    if est.tokens <= budget_tokens:
        return est

    template = str(dynamic.get("template") or "")
    if len(template) > 400:
        dynamic["template"] = template[:400] + "\n# …template truncado p/ budget"
        est = _count(SYSTEM, dynamic)
        if est.tokens <= budget_tokens:
            return est

    cons = str(dynamic.get("contexto_comprimido") or "")
    if cons and est.tokens > budget_tokens:
        overflow = est.tokens - budget_tokens
        cut = max(0, len(cons) - overflow * HEURISTIC_CHARS_PER_TOKEN)
        dynamic["contexto_comprimido"] = cons[:cut] + ("…" if cut < len(cons) else "")
        est = _count(SYSTEM, dynamic)
    return est


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

    est = _fit_to_budget(dynamic, budget_tokens)
    usage = est.to_telemetry()
    return {
        "system": SYSTEM,  # prefixo estável → prompt caching
        "dynamic": dynamic,
        "est_tokens": est.tokens,
        "est_tokens_method": est.method,
        "token_usage": usage,
        "rag_stats": {
            "raw": rag.get("est_tokens_raw"),
            "compressed": rag.get("est_tokens_compressed"),
            "method": est.method,
            "docs": (rag.get("documents") or {}).get("docs"),
            "doc_reduction_pct": (rag.get("documents") or {}).get("reduction_pct"),
        },
    }
