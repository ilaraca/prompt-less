"""
Compressão hierárquica de documentos (padrão do artigo):

  docs brutos → chunks → resumos de chunk → resumo consolidado ≤ budget
"""
from __future__ import annotations

import re
from typing import Any

SIGNAL_RE = re.compile(
    r"\b(regra|bloqueio|erro|http|endpoint|path|request|response|dado|quando|então|"
    r"obrigat|valid|auth|permiss|input|campo|api|bff|status|openapi|fluxo|fluxo)\b",
    re.I,
)


def _clip(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def chunk_text(text: str, lines_per_chunk: int = 40) -> list[str]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[str] = []
    for i in range(0, len(lines), lines_per_chunk):
        block = "\n".join(lines[i : i + lines_per_chunk]).strip()
        if block:
            chunks.append(block)
    return chunks


def summarize_chunk(chunk: str, max_chars: int = 220) -> str:
    """Extrativo local (camada 'modelo pequeno'): só linhas com sinal; senão stub."""
    lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    if not lines:
        return ""

    scored = [ln for ln in lines if SIGNAL_RE.search(ln)]
    if not scored:
        # sem sinal de negócio → não injeta telemetria/ruído no contexto
        return ""

    seen: set[str] = set()
    picked: list[str] = []
    for ln in scored:
        if ln not in seen:
            seen.add(ln)
            picked.append(ln)
        if len(" ".join(picked)) >= max_chars:
            break
    return _clip(" | ".join(picked), max_chars)


def consolidate_summaries(summaries: list[str], max_chars: int = 800) -> str:
    if not summaries:
        return ""
    # prioriza chunks com sinais de regra/API
    ranked = sorted(summaries, key=lambda s: (0 if SIGNAL_RE.search(s) else 1, -len(s)))
    out: list[str] = []
    total = 0
    for s in ranked:
        if not s:
            continue
        add = len(s) + (3 if out else 0)
        if total + add > max_chars:
            remain = max_chars - total - 1
            if remain > 40:
                out.append(_clip(s, remain))
            break
        out.append(s)
        total += add
    return " | ".join(out)


def compress_documents(
    docs: list[dict[str, Any]],
    *,
    lines_per_chunk: int = 40,
    chunk_summary_chars: int = 220,
    consolidated_chars: int = 800,
) -> dict[str, Any]:
    per_doc: list[dict[str, Any]] = []
    all_summaries: list[str] = []
    raw_tokens = 0

    for doc in docs:
        text = doc.get("text") or ""
        raw_tokens += doc.get("est_tokens_raw") or (len(text) // 4)
        chunks = chunk_text(text, lines_per_chunk=lines_per_chunk)
        summaries = [summarize_chunk(c, chunk_summary_chars) for c in chunks]
        summaries = [s for s in summaries if s]
        all_summaries.extend(summaries)
        per_doc.append(
            {
                "name": doc.get("name"),
                "lines": doc.get("lines"),
                "chunks": len(chunks),
                "est_tokens_raw": doc.get("est_tokens_raw") or (len(text) // 4),
                "chunk_summaries": summaries,
            }
        )

    consolidated = consolidate_summaries(all_summaries, max_chars=consolidated_chars)
    return {
        "doc_count": len(docs),
        "docs": [{"name": d["name"], "lines": d["lines"], "chunks": d["chunks"], "est_tokens_raw": d["est_tokens_raw"]} for d in per_doc],
        "chunk_summaries": all_summaries,
        "consolidated": consolidated,
        "est_tokens_raw": raw_tokens,
        "est_tokens_compressed": max(1, len(consolidated) // 4) if consolidated else 0,
        "reduction_pct": round(
            100
            * (
                1
                - (
                    len(consolidated)
                    / max(sum(len(d.get("text") or "") for d in docs), 1)
                )
            ),
            1,
        )
        if docs
        else 0.0,
    }
