"""
Compressão hierárquica de documentos (padrão do artigo):

  docs brutos → chunks → resumos de chunk → resumo consolidado ≤ budget

Preserva proveniência (DocumentChunk / Claim / descarte).
"""
from __future__ import annotations

import re
from typing import Any

from src.domain.claim import Claim, ClaimOrigin
from src.domain.chunk import ChunkSummary, DocumentChunk, content_hash
from src.domain.source_ref import SourceRef

SIGNAL_RE = re.compile(
    r"\b(regra|bloqueio|erro|http|endpoint|path|request|response|dado|quando|então|"
    r"obrigat|valid|auth|permiss|input|campo|api|bff|status|openapi|fluxo|fluxo)\b",
    re.I,
)

SECTION_RE = re.compile(r"^(#{1,6}\s+.+|\d+[\.\)]\s+.+|[A-ZÁÉÍÓÚÂÊÔÃÕ][^\n]{0,80})$")


def _clip(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _detect_signals(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in SIGNAL_RE.finditer(text)})


def _section_hint(text: str) -> str | None:
    for ln in text.splitlines():
        s = ln.strip()
        if s and SECTION_RE.match(s) and len(s) < 100:
            return s[:80]
    return None


def chunk_text(text: str, lines_per_chunk: int = 40) -> list[str]:
    """API legada: lista de strings."""
    return [c.raw_text for c in build_document_chunks({"name": "_", "text": text}, lines_per_chunk)]


def build_document_chunks(
    doc: dict[str, Any],
    lines_per_chunk: int = 40,
    *,
    counter_start: int = 1,
) -> list[DocumentChunk]:
    text = doc.get("text") or ""
    name = str(doc.get("name") or "unknown")
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[DocumentChunk] = []
    n = counter_start
    for i in range(0, len(lines), lines_per_chunk):
        block_lines = lines[i : i + lines_per_chunk]
        block = "\n".join(block_lines).strip()
        if not block:
            continue
        start = i + 1
        end = i + len(block_lines)
        signals = _detect_signals(block)
        chunks.append(
            DocumentChunk(
                id=f"CHK-{n:04d}",
                document=name,
                section=_section_hint(block),
                start_line=start,
                end_line=end,
                raw_text=block,
                content_hash=content_hash(block),
                service_id=doc.get("service_id"),
                signals=signals,
                score=float(len(signals)),
            )
        )
        n += 1
    return chunks


def summarize_chunk(chunk: str, max_chars: int = 220) -> str:
    """API legada: retorna só o texto do resumo."""
    fake = DocumentChunk(
        id="CHK-TEMP",
        document="_",
        section=None,
        start_line=1,
        end_line=max(1, chunk.count("\n") + 1),
        raw_text=chunk,
        content_hash=content_hash(chunk),
        signals=_detect_signals(chunk),
    )
    return summarize_document_chunk(fake, max_chars=max_chars).summary


def summarize_document_chunk(chunk: DocumentChunk, max_chars: int = 220) -> ChunkSummary:
    raw_lines = chunk.raw_text.splitlines()
    if not any(ln.strip() for ln in raw_lines):
        return ChunkSummary(
            chunk_id=chunk.id,
            summary="",
            selected_lines=[],
            signals=[],
            discarded=True,
            reason="empty_chunk",
            document=chunk.document,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content_hash=chunk.content_hash,
        )

    scored: list[tuple[int, str]] = []
    for i, ln in enumerate(raw_lines):
        stripped = ln.strip()
        if stripped and SIGNAL_RE.search(stripped):
            scored.append((chunk.start_line + i, stripped))

    if not scored:
        return ChunkSummary(
            chunk_id=chunk.id,
            summary="",
            selected_lines=[],
            signals=[],
            discarded=True,
            reason="no_known_signal",
            recoverable=True,
            document=chunk.document,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content_hash=chunk.content_hash,
        )

    seen: set[str] = set()
    picked: list[str] = []
    selected: list[int] = []
    for line_no, ln in scored:
        if ln not in seen:
            seen.add(ln)
            picked.append(ln)
            selected.append(line_no)
        if len(" ".join(picked)) >= max_chars:
            break

    return ChunkSummary(
        chunk_id=chunk.id,
        summary=_clip(" | ".join(picked), max_chars),
        selected_lines=selected,
        signals=chunk.signals or _detect_signals(" ".join(picked)),
        discarded=False,
        document=chunk.document,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        content_hash=chunk.content_hash,
    )


def claim_from_summary(summary: ChunkSummary, claim_id: str) -> Claim | None:
    if summary.discarded or not summary.summary:
        return None
    return Claim(
        id=claim_id,
        text=summary.summary,
        origin=ClaimOrigin.DECLARED,
        confidence=1.0,
        sources=[
            SourceRef(
                document=summary.document or "unknown",
                start_line=summary.start_line,
                end_line=summary.end_line,
                content_hash=summary.content_hash,
            )
        ],
        chunk_id=summary.chunk_id,
        requires_review=False,
    )


def consolidate_summaries(summaries: list[str], max_chars: int = 800) -> str:
    if not summaries:
        return ""
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


def consolidate_chunk_summaries(
    summaries: list[ChunkSummary],
    max_chars: int = 800,
) -> tuple[str, list[dict[str, Any]]]:
    """Consolida respeitando budget e reporta omissões por budget."""
    kept = [s for s in summaries if not s.discarded and s.summary]
    ranked = sorted(kept, key=lambda s: (0 if s.signals else 1, -len(s.summary)))
    out: list[str] = []
    included_ids: set[str] = set()
    total = 0
    omitted_budget: list[dict[str, Any]] = []

    for s in ranked:
        add = len(s.summary) + (3 if out else 0)
        if total + add > max_chars:
            omitted_budget.append(
                {
                    "chunk_id": s.chunk_id,
                    "discarded": True,
                    "reason": "budget_exceeded",
                    "recoverable": True,
                    "document": s.document,
                }
            )
            continue
        out.append(s.summary)
        included_ids.add(s.chunk_id)
        total += add

    # se nada coube mas havia candidatos, tenta clip do primeiro
    if not out and ranked:
        first = ranked[0]
        out.append(_clip(first.summary, max_chars))
        included_ids.add(first.chunk_id)
        omitted_budget = [o for o in omitted_budget if o["chunk_id"] != first.chunk_id]

    return " | ".join(out), omitted_budget


def compress_documents(
    docs: list[dict[str, Any]],
    *,
    lines_per_chunk: int = 40,
    chunk_summary_chars: int = 220,
    consolidated_chars: int = 800,
) -> dict[str, Any]:
    per_doc: list[dict[str, Any]] = []
    all_chunk_objs: list[DocumentChunk] = []
    all_summaries: list[ChunkSummary] = []
    claims: list[Claim] = []
    discarded: list[dict[str, Any]] = []
    raw_tokens = 0
    counter = 1
    claim_n = 1

    for doc in docs:
        text = doc.get("text") or ""
        raw_tokens += doc.get("est_tokens_raw") or (len(text) // 4)
        chunks = build_document_chunks(doc, lines_per_chunk, counter_start=counter)
        counter += len(chunks)
        all_chunk_objs.extend(chunks)

        doc_summaries: list[str] = []
        for ch in chunks:
            summary = summarize_document_chunk(ch, max_chars=chunk_summary_chars)
            all_summaries.append(summary)
            if summary.discarded:
                discarded.append(summary.to_dict())
            else:
                doc_summaries.append(summary.summary)
                claim = claim_from_summary(summary, f"CLM-{claim_n:04d}")
                claim_n += 1
                if claim:
                    claims.append(claim)

        per_doc.append(
            {
                "name": doc.get("name"),
                "lines": doc.get("lines"),
                "chunks": len(chunks),
                "est_tokens_raw": doc.get("est_tokens_raw") or (len(text) // 4),
                "chunk_summaries": doc_summaries,
            }
        )

    consolidated, omitted_budget = consolidate_chunk_summaries(
        all_summaries, max_chars=consolidated_chars
    )
    discarded.extend(omitted_budget)

    # claims cujo chunk foi cortado pelo budget → marcar review
    omitted_ids = {o["chunk_id"] for o in omitted_budget}
    for claim in claims:
        if claim.chunk_id in omitted_ids:
            claim.requires_review = True
            claim.confidence = min(claim.confidence, 0.5)

    kept_claims = [c for c in claims if c.chunk_id not in omitted_ids]

    return {
        "doc_count": len(docs),
        "docs": [
            {
                "name": d["name"],
                "lines": d["lines"],
                "chunks": d["chunks"],
                "est_tokens_raw": d["est_tokens_raw"],
            }
            for d in per_doc
        ],
        "chunk_summaries": [s.summary for s in all_summaries if s.summary and not s.discarded],
        "chunk_summaries_structured": [s.to_dict() for s in all_summaries],
        "chunks": [c.to_dict() for c in all_chunk_objs],
        "claims": [c.to_dict() for c in kept_claims],
        "discarded": discarded,
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
