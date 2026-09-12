"""RAG + compressão hierárquica: UI/regras + docs → consolidated ≤ budget."""
from __future__ import annotations

from typing import Any

from src.doc_compress import compress_documents
from src.domain.claim import Claim, ClaimOrigin
from src.domain.source_ref import SourceRef
from src.engenharia import rag_snippet


def _clip(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def retrieve_chunks(ctx: dict[str, Any]) -> list[dict[str, str]]:
    """Fatia UI + regras em chunks curtos (sem dumps brutos)."""
    chunks: list[dict[str, str]] = []
    ui = ctx.get("ui") or {}
    regras = ctx.get("regras") or {}

    if ui.get("inputs"):
        props = ", ".join(f"{i['name']}:{i['type']}" for i in ui["inputs"])
        chunks.append({"id": "ui.inputs", "text": f"inputs[{props}]"})

    if ui.get("columns"):
        cols = ", ".join(f"{c['name']}:{c['type']}" for c in ui["columns"])
        chunks.append({"id": "ui.columns", "text": f"response_cols[{cols}]"})

    if ui.get("actions"):
        acts = ", ".join(
            f"{a.get('id')}:{a.get('method') or '?'}{a.get('path') or ''}" for a in ui["actions"]
        )
        chunks.append({"id": "ui.actions", "text": f"actions[{acts}]"})

    for i, b in enumerate(regras.get("bloqueios") or []):
        chunks.append(
            {
                "id": f"rule.block.{i}",
                "text": f"block status={b.get('status')} trigger={b.get('trigger')}",
            }
        )

    for i, d in enumerate(regras.get("decisoes") or []):
        chunks.append({"id": f"rule.decision.{i}", "text": _clip(str(d), 180)})

    eng = ctx.get("engenharia") or {}
    if eng:
        chunks.append({"id": "eng.baseline", "text": rag_snippet(eng)})

    return chunks


def summarize_chunks(chunks: list[dict[str, str]], max_chars: int = 160) -> list[str]:
    return [_clip(c["text"], max_chars) for c in chunks]


def consolidate(summaries: list[str], max_chars: int = 800) -> str:
    joined = " | ".join(s for s in summaries if s)
    return _clip(joined, max_chars)


def compress_rag(
    ctx: dict[str, Any],
    *,
    consolidated_chars: int = 800,
    lines_per_chunk: int = 40,
    chunk_summary_chars: int = 220,
) -> dict[str, Any]:
    struct_chunks = retrieve_chunks(ctx)
    struct_summaries = summarize_chunks(struct_chunks)
    struct_part = consolidate(struct_summaries, max_chars=max(200, consolidated_chars // 3))

    docs = ctx.get("documents") or []
    doc_budget = max(200, consolidated_chars - len(struct_part) - 3)
    docs_part = compress_documents(
        docs,
        lines_per_chunk=lines_per_chunk,
        chunk_summary_chars=chunk_summary_chars,
        consolidated_chars=doc_budget,
    )

    parts = [p for p in (struct_part, docs_part.get("consolidated") or "") if p]
    consolidated = consolidate(parts, max_chars=consolidated_chars)

    # claims estruturados das regras (declared)
    struct_claims: list[dict] = []
    n = 1
    for i, b in enumerate((ctx.get("regras") or {}).get("bloqueios") or []):
        text = f"block status={b.get('status')} trigger={b.get('trigger')}"
        struct_claims.append(
            Claim(
                id=f"CLM-R{n:03d}",
                text=text,
                origin=ClaimOrigin.DECLARED,
                confidence=1.0,
                sources=[SourceRef(document="regras.yaml", section=f"bloqueios[{i}]")],
            ).to_dict()
        )
        n += 1

    raw_tokens = (sum(len(c["text"]) for c in struct_chunks) // 4) + int(
        docs_part.get("est_tokens_raw") or 0
    )
    return {
        "chunk_count": len(struct_chunks) + sum(d.get("chunks", 0) for d in docs_part.get("docs") or []),
        "summaries": struct_summaries + (docs_part.get("chunk_summaries") or []),
        "consolidated": consolidated,
        "documents": docs_part,
        "claims": struct_claims + list(docs_part.get("claims") or []),
        "discarded": list(docs_part.get("discarded") or []),
        "est_tokens_raw": raw_tokens,
        "est_tokens_compressed": max(1, len(consolidated) // 4) if consolidated else 0,
    }
