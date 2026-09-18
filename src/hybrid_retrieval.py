"""
Recuperação híbrida de documentos (ticket 26).

Roteia por estrutura do insumo:
  structured → âncoras de seção (doc_preface.parse_sections + TF-IDF)
  flat       → caminho lexical atual (doc_compress)

Primeira camada sempre estrutural/lexical e barata. Segunda camada semântica
é opcional, limitada por budget, com fallback local (sinônimos + cosseno TF)
sem provider externo. Índice invertido por seção fica em state/, nunca no prompt.
Secrets/PII são removidos antes de qualquer camada semântica.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.doc_compress import (  # noqa: E402
    SIGNAL_RE,
    _clip,
    summarize_document_chunk,
)
from src.doc_preface import (  # noqa: E402
    Section,
    build_inverted,
    parse_sections,
    tokenize,
)
from src.domain.claim import Claim, ClaimOrigin  # noqa: E402
from src.domain.chunk import DocumentChunk, content_hash  # noqa: E402
from src.domain.provenance import make_claim_id  # noqa: E402
from src.domain.source_ref import SourceRef  # noqa: E402
from src.hardening.input_scan import (  # noqa: E402
    _CARD_RE,
    _CPF_RE,
    _EMAIL_RE,
    _PHONE_BR_RE,
    _SECRET_PATTERNS,
)
from src.tokenizer import count_tokens, est_raw  # noqa: E402

SECTION_INDEX_NAME = "doc_section_index.json"

# Títulos markdown (#), numerados e rótulos SEÇÃO/CAPÍTULO — alinhado a marcar/doc_preface
HEADING_DETECT_RE = re.compile(
    r"^\s*(?:#{1,6}\s+\S|\d+(?:\.\d+)*[.)]?\s+\S|(?:SE[CÇ][AÃ]O|CAP[IÍ]TULO|ANEXO)\b)",
    re.I,
)

# Sinônimos locais para a 2ª camada (sem embeddings externos)
LOCAL_SYNONYMS: dict[str, frozenset[str]] = {
    "cpf": frozenset({"cpf", "documento", "identificacao", "titular", "cadastro"}),
    "bloqueio": frozenset({"bloqueio", "recusa", "rejeita", "impede", "nega", "recusar"}),
    "auth": frozenset({"auth", "autenticacao", "login", "credencial", "sessao", "token"}),
    "permiss": frozenset({"permiss", "autorizacao", "acesso", "privilegio", "role"}),
    "endpoint": frozenset({"endpoint", "rota", "path", "url", "api", "recurso"}),
    "erro": frozenset({"erro", "falha", "invalido", "invalida", "negado", "recusado"}),
    "status": frozenset({"status", "http", "codigo", "resposta"}),
    "obrigat": frozenset({"obrigat", "requer", "exige", "necessario", "mandatorio"}),
}


@dataclass
class StructureEvidence:
    kind: str  # structured | flat
    heading_count: int
    signal_line_count: int
    total_lines: int
    signal_density: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievedHit:
    text: str
    source: SourceRef
    score: float
    strategy: str
    document: str
    section_id: str | None = None
    chunk_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source.to_dict(),
            "score": round(self.score, 4),
            "strategy": self.strategy,
            "document": self.document,
            "section_id": self.section_id,
            "chunk_id": self.chunk_id,
        }


@dataclass
class HybridTelemetry:
    structure: list[dict[str, Any]] = field(default_factory=list)
    strategies_used: list[str] = field(default_factory=list)
    semantic_enabled: bool = False
    semantic_provider: str = "none"
    semantic_chars_used: int = 0
    semantic_budget_chars: int = 0
    semantic_hits: int = 0
    scrubbed_spans: int = 0
    index_path: str | None = None
    est_tokens_semantic: int = 0
    cost_note: str = "semantic_local_zero_external"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_structure(
    text: str,
    *,
    min_headings: int = 2,
) -> StructureEvidence:
    """Classifica o insumo como structured|flat com evidência mensurável."""
    lines = text.splitlines()
    total = max(1, len(lines))
    heading_count = sum(1 for ln in lines if HEADING_DETECT_RE.match(ln))
    signal_line_count = sum(1 for ln in lines if ln.strip() and SIGNAL_RE.search(ln))
    density = round(signal_line_count / total, 4)
    if heading_count >= min_headings:
        return StructureEvidence(
            kind="structured",
            heading_count=heading_count,
            signal_line_count=signal_line_count,
            total_lines=total,
            signal_density=density,
            reason=f"heading_count={heading_count}>={min_headings}",
        )
    return StructureEvidence(
        kind="flat",
        heading_count=heading_count,
        signal_line_count=signal_line_count,
        total_lines=total,
        signal_density=density,
        reason=f"heading_count={heading_count}<{min_headings}; signal_density={density}",
    )


def scrub_sensitive(text: str) -> tuple[str, int]:
    """Remove secrets/PII antes de embeddings ou LLM. Retorna (texto, nº de spans)."""
    if not text:
        return text, 0
    count = 0
    out = text
    for _code, pat in _SECRET_PATTERNS:
        out, n = pat.subn("[REDACTED_SECRET]", out)
        count += n
    out, n = _CPF_RE.subn("[REDACTED_CPF]", out)
    count += n
    out, n = _CARD_RE.subn("[REDACTED_CARD]", out)
    count += n
    out, n = _EMAIL_RE.subn("[REDACTED_EMAIL]", out)
    count += n
    out, n = _PHONE_BR_RE.subn("[REDACTED_PHONE]", out)
    count += n
    return out, count


def build_query_from_ctx(ctx: dict[str, Any] | None) -> str:
    """Query barata a partir de regras/UI — sem texto bruto de docs."""
    ctx = ctx or {}
    parts: list[str] = []
    regras = ctx.get("regras") or {}
    if regras.get("bloqueios"):
        parts.append("bloqueio recusa erro")
    for b in regras.get("bloqueios") or []:
        parts.append(str(b.get("trigger") or ""))
        parts.append(str(b.get("status") or ""))
        parts.append(str(b.get("code") or ""))
    for d in regras.get("decisoes") or []:
        parts.append(str(d))
    ui = ctx.get("ui") or {}
    if ui.get("actions") or ui.get("inputs"):
        parts.append("auth permiss endpoint api")
    for a in ui.get("actions") or []:
        parts.append(str(a.get("method") or ""))
        parts.append(str(a.get("path") or ""))
        parts.append(str(a.get("id") or ""))
    for i in ui.get("inputs") or []:
        parts.append(str(i.get("name") or ""))
    return " ".join(p for p in parts if p).strip()


def _expand_query_terms(query: str) -> set[str]:
    base = set(tokenize(query))
    # também captura tokens curtos de SIGNAL_RE no query bruto
    for m in SIGNAL_RE.finditer(query):
        base.add(m.group(0).lower())
    expanded = set(base)
    for term in list(base):
        for key, syns in LOCAL_SYNONYMS.items():
            if term == key or term.startswith(key) or key in term or term in syns:
                expanded |= set(syns)
    return expanded


def _tf_vector(text: str, vocab: set[str] | None = None) -> dict[str, float]:
    toks = tokenize(text)
    if vocab is not None:
        toks = [t for t in toks if t in vocab]
    if not toks:
        return {}
    counts: dict[str, int] = {}
    for t in toks:
        counts[t] = counts.get(t, 0) + 1
    norm = float(len(toks))
    return {t: c / norm for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _section_signal_score(sec: Section) -> float:
    lines = [ln for ln in sec.text.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    hits = sum(1 for ln in lines if SIGNAL_RE.search(ln))
    return hits / len(lines)


def _score_section_tfidf(
    sec: Section,
    query_terms: set[str],
    idf: dict[str, float],
) -> float:
    if not query_terms:
        return _section_signal_score(sec)
    blob = f"{sec.heading}\n{sec.text}"
    tf = _tf_vector(blob)
    score = 0.0
    for term in query_terms:
        if term in tf:
            score += tf[term] * idf.get(term, 1.0)
        else:
            # prefix match for stems like permiss/auth
            for tok, w in tf.items():
                if tok.startswith(term) or term.startswith(tok):
                    score += w * idf.get(tok, 1.0) * 0.5
    return score


def _summarize_section(sec: Section, *, max_chars: int = 220) -> tuple[str, list[int]]:
    """Extrai linhas com sinal; se vazio, primeiras linhas não-vazias (âncora estruturada)."""
    picked: list[str] = []
    selected: list[int] = []
    for i, ln in enumerate(sec.text.splitlines()):
        stripped = ln.strip()
        if not stripped:
            continue
        line_no = sec.start_line + i
        if SIGNAL_RE.search(stripped):
            if stripped not in picked:
                picked.append(stripped)
                selected.append(line_no)
            if len(" ".join(picked)) >= max_chars:
                break
    if not picked:
        for i, ln in enumerate(sec.text.splitlines()):
            stripped = ln.strip()
            if not stripped or stripped.startswith("#"):
                continue
            picked.append(stripped)
            selected.append(sec.start_line + i)
            if len(" ".join(picked)) >= max_chars:
                break
    return _clip(" | ".join(picked), max_chars), selected


def persist_section_index(
    document: str,
    sections: list[Section],
    inverted: dict[str, list[str]],
    idf: dict[str, float],
    evidence: StructureEvidence,
    *,
    state_dir: Path,
) -> Path:
    """Índice invertido por seção em state/ — nunca no prompt."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / SECTION_INDEX_NAME
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    docs = dict(existing.get("documents") or {})
    body = "\n".join(s.text for s in sections)
    docs[document] = {
        "kind": evidence.kind,
        "evidence": evidence.to_dict(),
        "body_hash": content_hash(body),
        "sections": [
            {
                "id": s.id,
                "heading": s.heading,
                "level": s.level,
                "start_line": s.start_line,
                "end_line": s.end_line,
            }
            for s in sections
        ],
        "inverted": inverted,
        "idf": {k: round(v, 4) for k, v in idf.items()},
    }
    payload = {"documents": docs, "note": "não incluir no prompt do modelo"}
    # import tardio: evita ciclo hybrid → runtime.handlers → hybrid
    from src.runtime.atomic_io import atomic_write_json
    atomic_write_json(path, payload)
    return path


def dedupe_hits(hits: list[RetrievedHit], *, max_hits: int | None = None) -> list[RetrievedHit]:
    """Deduplica por content_hash preservando diversidade de fontes (round-robin)."""
    by_doc: dict[str, list[RetrievedHit]] = {}
    for h in sorted(hits, key=lambda x: -x.score):
        by_doc.setdefault(h.document, []).append(h)

    seen_hash: set[str] = set()
    seen_text: set[str] = set()
    out: list[RetrievedHit] = []
    # round-robin entre documentos
    pointers = {d: 0 for d in by_doc}
    while pointers:
        progressed = False
        for doc in list(pointers):
            bucket = by_doc[doc]
            idx = pointers[doc]
            while idx < len(bucket):
                hit = bucket[idx]
                idx += 1
                ch = hit.source.content_hash or content_hash(hit.text)
                norm = " ".join(hit.text.lower().split())
                if ch in seen_hash or norm in seen_text:
                    continue
                seen_hash.add(ch)
                seen_text.add(norm)
                out.append(hit)
                progressed = True
                break
            if idx >= len(bucket):
                pointers.pop(doc, None)
            else:
                pointers[doc] = idx
            if max_hits is not None and len(out) >= max_hits:
                return out
        if not progressed:
            break
    return out


def _retrieve_structured(
    doc: dict[str, Any],
    *,
    query: str,
    chunk_summary_chars: int,
    state_dir: Path | None,
    telemetry: HybridTelemetry,
) -> list[RetrievedHit]:
    name = str(doc.get("name") or "unknown")
    text = str(doc.get("text") or "")
    evidence = detect_structure(text)
    sections = parse_sections(text)
    inverted, idf = build_inverted(sections)
    if state_dir is not None:
        path = persist_section_index(
            name, sections, inverted, idf, evidence, state_dir=state_dir
        )
        telemetry.index_path = str(path)

    query_terms = _expand_query_terms(query) if query else set()
    hits: list[RetrievedHit] = []
    for sec in sections:
        if sec.id in {"corpo"} and evidence.kind == "flat":
            continue
        score = _score_section_tfidf(sec, query_terms, idf)
        if score <= 0 and not SIGNAL_RE.search(sec.text):
            # seção sem sinal e sem match — pula na 1ª camada
            continue
        summary, selected = _summarize_section(sec, max_chars=chunk_summary_chars)
        if not summary:
            continue
        # score mínimo estrutural quando há sinal
        final_score = max(score, _section_signal_score(sec) * 0.5, 0.01)
        hits.append(
            RetrievedHit(
                text=summary,
                source=SourceRef(
                    document=name,
                    section=sec.heading,
                    start_line=sec.start_line,
                    end_line=sec.end_line,
                    content_hash=content_hash(sec.text),
                    selected_lines=tuple(selected) if selected else None,
                ),
                score=final_score,
                strategy="structural_anchor",
                document=name,
                section_id=sec.id,
                chunk_id=f"SEC-{sec.id}",
            )
        )
    return hits


def _retrieve_flat(
    doc: dict[str, Any],
    *,
    lines_per_chunk: int,
    chunk_summary_chars: int,
    counter_start: int,
) -> tuple[list[RetrievedHit], list[DocumentChunk], list[dict[str, Any]]]:
    """Mantém o caminho doc_compress (chunk + SIGNAL_RE) sem regressão."""
    from src.doc_compress import build_document_chunks

    name = str(doc.get("name") or "unknown")
    chunks = build_document_chunks(doc, lines_per_chunk, counter_start=counter_start)
    hits: list[RetrievedHit] = []
    discarded: list[dict[str, Any]] = []
    for ch in chunks:
        summary = summarize_document_chunk(ch, max_chars=chunk_summary_chars)
        if summary.discarded:
            discarded.append(summary.to_dict())
            continue
        score = float(len(ch.signals) or len(summary.signals) or 0) + ch.score
        hits.append(
            RetrievedHit(
                text=summary.summary,
                source=SourceRef(
                    document=name,
                    section=ch.section,
                    start_line=ch.start_line,
                    end_line=ch.end_line,
                    content_hash=ch.content_hash,
                    selected_lines=tuple(summary.selected_lines) if summary.selected_lines else None,
                ),
                score=max(score, 0.01),
                strategy="lexical_flat",
                document=name,
                chunk_id=ch.id,
            )
        )
    return hits, chunks, discarded



def _semantic_summary(text: str, query_terms: set[str], *, max_chars: int = 220) -> str:
    """Prefere linhas com overlap semântico; evita preencher o budget com ruído."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    scored: list[tuple[float, str]] = []
    for ln in lines:
        toks = set(tokenize(ln))
        overlap = len(toks & query_terms) / max(1, len(query_terms))
        # ruído óbvio de telemetria perde
        if ln.lower().startswith("ruido de telemetria"):
            overlap *= 0.05
        scored.append((overlap, ln))
    scored.sort(key=lambda x: -x[0])
    picked: list[str] = []
    for score, ln in scored:
        if score <= 0 and picked:
            continue
        picked.append(ln)
        if len(" ".join(picked)) >= max_chars:
            break
    if not picked:
        picked = lines[:3]
    return _clip(" | ".join(picked), max_chars)


def _semantic_local_layer(
    docs: list[dict[str, Any]],
    query: str,
    *,
    existing: list[RetrievedHit],
    discarded: list[dict[str, Any]],
    budget_chars: int,
    lines_per_chunk: int,
) -> tuple[list[RetrievedHit], int, int]:
    """
    2ª camada local: expande sinônimos e recupera trechos descartados / narrativos.
    Sem provider externo. Respeita budget de caracteres.
    """
    if budget_chars <= 0:
        return [], 0, 0
    query_terms = _expand_query_terms(query) if query else set(LOCAL_SYNONYMS)
    # vocab união para cosseno
    vocab = set(query_terms)
    for syns in LOCAL_SYNONYMS.values():
        vocab |= set(syns)
    q_vec = {t: 1.0 for t in query_terms} if query_terms else {t: 1.0 for t in vocab}

    existing_hashes = {h.source.content_hash for h in existing if h.source.content_hash}
    existing_texts = {" ".join(h.text.lower().split()) for h in existing}
    candidates: list[RetrievedHit] = []

    # 1) discarded recoverable do flat path
    for d in discarded:
        if not d.get("recoverable"):
            continue
        # reconstruir texto aproximado das linhas do chunk via docs
        doc_name = str(d.get("document") or "")
        start = int(d.get("start_line") or 1)
        end = int(d.get("end_line") or start)
        raw = ""
        for doc in docs:
            if str(doc.get("name") or "") != doc_name:
                continue
            lines = str(doc.get("text") or "").splitlines()
            raw = "\n".join(lines[start - 1 : end])
            break
        if not raw.strip():
            continue
        scrubbed, _ = scrub_sensitive(raw)
        score = _cosine(_tf_vector(scrubbed, vocab), q_vec)
        # também conta overlap lexical expandido
        toks = set(tokenize(scrubbed))
        overlap = len(toks & query_terms) / max(1, len(query_terms))
        score = max(score, overlap)
        if score < 0.08:
            continue
        summary = _semantic_summary(scrubbed, query_terms, max_chars=220)
        if not summary:
            continue
        chash = content_hash(scrubbed)
        if chash in existing_hashes:
            continue
        candidates.append(
            RetrievedHit(
                text=summary,
                source=SourceRef(
                    document=doc_name or "unknown",
                    section=d.get("section"),
                    start_line=start,
                    end_line=end,
                    content_hash=chash,
                ),
                score=score,
                strategy="semantic_local",
                document=doc_name or "unknown",
                chunk_id=str(d.get("chunk_id") or ""),
            )
        )

    # 2) chunks flat sem sinal lexical mas com overlap semântico (docs flat)
    from src.doc_compress import build_document_chunks

    for doc in docs:
        evidence = detect_structure(str(doc.get("text") or ""))
        if evidence.kind != "flat":
            continue
        name = str(doc.get("name") or "unknown")
        for ch in build_document_chunks(doc, lines_per_chunk):
            if ch.signals:
                continue
            scrubbed, _ = scrub_sensitive(ch.raw_text)
            score = _cosine(_tf_vector(scrubbed, vocab), q_vec)
            toks = set(tokenize(scrubbed))
            overlap = len(toks & query_terms) / max(1, len(query_terms))
            score = max(score, overlap)
            if score < 0.12:
                continue
            if ch.content_hash in existing_hashes:
                continue
            summary = _semantic_summary(scrubbed, query_terms, max_chars=220)
            if not summary or " ".join(summary.lower().split()) in existing_texts:
                continue
            candidates.append(
                RetrievedHit(
                    text=summary,
                    source=SourceRef(
                        document=name,
                        section=ch.section,
                        start_line=ch.start_line,
                        end_line=ch.end_line,
                        content_hash=ch.content_hash,
                    ),
                    score=score,
                    strategy="semantic_local",
                    document=name,
                    chunk_id=ch.id,
                )
            )

    candidates.sort(key=lambda h: -h.score)
    kept: list[RetrievedHit] = []
    used = 0
    for hit in candidates:
        add = len(hit.text) + (3 if kept else 0)
        if used + add > budget_chars:
            continue
        kept.append(hit)
        used += add
    return kept, used, len(kept)


def _hits_to_claims(
    hits: list[RetrievedHit],
    *,
    service_id: str | None,
    claim_start: int = 1,
) -> list[Claim]:
    claims: list[Claim] = []
    n = claim_start
    for hit in hits:
        claims.append(
            Claim(
                id=make_claim_id(n),
                text=hit.text,
                origin=ClaimOrigin.DECLARED,
                confidence=min(1.0, max(0.1, hit.score if hit.score <= 1.0 else hit.score / 10.0)),
                sources=[hit.source],
                service_id=service_id,
                chunk_id=hit.chunk_id,
                retrieval_score=round(hit.score, 4),
                retrieval_strategy=hit.strategy,
            )
        )
        n += 1
    return claims


def compress_documents_hybrid(
    docs: list[dict[str, Any]],
    *,
    query: str = "",
    lines_per_chunk: int = 40,
    chunk_summary_chars: int = 220,
    consolidated_chars: int = 800,
    service_id: str | None = None,
    enable_semantic: bool = True,
    semantic_budget_chars: int | None = None,
    state_dir: Path | None = None,
    min_headings: int = 2,
) -> dict[str, Any]:
    """
    Compressão documental com roteador structured|flat + camada semântica opcional.

    Saída compatível com compress_documents (+ campos hybrid/telemetry/retrieved).
    """
    state_dir = Path(state_dir) if state_dir is not None else ROOT / "state"
    if semantic_budget_chars is None:
        semantic_budget_chars = max(120, consolidated_chars // 4)

    telemetry = HybridTelemetry(
        semantic_enabled=bool(enable_semantic),
        semantic_provider="local" if enable_semantic else "none",
        semantic_budget_chars=int(semantic_budget_chars),
    )

    all_hits: list[RetrievedHit] = []
    all_discarded: list[dict[str, Any]] = []
    all_chunks: list[DocumentChunk] = []
    structure_meta: list[dict[str, Any]] = []
    scrubbed_docs: list[dict[str, Any]] = []
    raw_tokens = 0
    counter = 1
    total_scrub = 0

    for doc in docs:
        text = str(doc.get("text") or "")
        raw_tokens += int(doc.get("est_tokens_raw") or est_raw(text))
        scrubbed_text, n_scrub = scrub_sensitive(text)
        total_scrub += n_scrub
        scrubbed = {**doc, "text": scrubbed_text}
        scrubbed_docs.append(scrubbed)

        evidence = detect_structure(scrubbed_text, min_headings=min_headings)
        structure_meta.append({"document": doc.get("name"), **evidence.to_dict()})

        if evidence.kind == "structured":
            hits = _retrieve_structured(
                scrubbed,
                query=query,
                chunk_summary_chars=chunk_summary_chars,
                state_dir=state_dir,
                telemetry=telemetry,
            )
            all_hits.extend(hits)
            if "structural_anchor" not in telemetry.strategies_used:
                telemetry.strategies_used.append("structural_anchor")
        else:
            hits, chunks, discarded = _retrieve_flat(
                scrubbed,
                lines_per_chunk=lines_per_chunk,
                chunk_summary_chars=chunk_summary_chars,
                counter_start=counter,
            )
            counter += len(chunks)
            all_hits.extend(hits)
            all_chunks.extend(chunks)
            all_discarded.extend(discarded)
            if "lexical_flat" not in telemetry.strategies_used:
                telemetry.strategies_used.append("lexical_flat")

    telemetry.scrubbed_spans = total_scrub
    telemetry.structure = structure_meta

    # 1ª camada: dedupe + budget do consolidado principal
    primary = dedupe_hits(all_hits)
    # ordena por score e cabe no budget (reservando fatia semântica)
    reserve = int(semantic_budget_chars) if enable_semantic else 0
    primary_budget = max(200, consolidated_chars - reserve)
    consolidated_parts: list[str] = []
    kept_primary: list[RetrievedHit] = []
    used = 0
    omitted_budget: list[dict[str, Any]] = []
    for hit in sorted(primary, key=lambda h: -h.score):
        add = len(hit.text) + (3 if consolidated_parts else 0)
        if used + add > primary_budget:
            omitted_budget.append(
                {
                    "chunk_id": hit.chunk_id,
                    "discarded": True,
                    "reason": "budget_exceeded",
                    "recoverable": True,
                    "document": hit.document,
                    "strategy": hit.strategy,
                }
            )
            continue
        consolidated_parts.append(hit.text)
        kept_primary.append(hit)
        used += add

    semantic_hits: list[RetrievedHit] = []
    if enable_semantic:
        semantic_hits, sem_chars, sem_n = _semantic_local_layer(
            scrubbed_docs,
            query,
            existing=kept_primary,
            discarded=all_discarded + omitted_budget,
            budget_chars=int(semantic_budget_chars),
            lines_per_chunk=lines_per_chunk,
        )
        telemetry.semantic_chars_used = sem_chars
        telemetry.semantic_hits = sem_n
        telemetry.est_tokens_semantic = count_tokens(" ".join(h.text for h in semantic_hits)) if semantic_hits else 0
        if semantic_hits and "semantic_local" not in telemetry.strategies_used:
            telemetry.strategies_used.append("semantic_local")
        for hit in semantic_hits:
            add = len(hit.text) + (3 if consolidated_parts else 0)
            if used + add > consolidated_chars:
                break
            consolidated_parts.append(hit.text)
            kept_primary.append(hit)
            used += add

    final_hits = dedupe_hits(kept_primary)
    consolidated = " | ".join(h.text for h in final_hits)
    if len(consolidated) > consolidated_chars:
        consolidated = _clip(consolidated, consolidated_chars)

    claims = _hits_to_claims(final_hits, service_id=service_id)
    discarded = all_discarded + omitted_budget

    # espelha shape de compress_documents para compatibilidade
    return {
        "doc_count": len(docs),
        "docs": [
            {
                "name": d.get("name"),
                "lines": d.get("lines") or len(str(d.get("text") or "").splitlines()),
                "chunks": sum(1 for h in final_hits if h.document == d.get("name")),
                "est_tokens_raw": d.get("est_tokens_raw") or est_raw(str(d.get("text") or "")),
                "structure": next(
                    (s for s in structure_meta if s.get("document") == d.get("name")),
                    None,
                ),
            }
            for d in docs
        ],
        "chunk_summaries": [h.text for h in final_hits],
        "chunk_summaries_structured": [
            {
                "chunk_id": h.chunk_id,
                "summary": h.text,
                "score": h.score,
                "strategy": h.strategy,
                "document": h.document,
                "section": h.source.section,
                "start_line": h.source.start_line,
                "end_line": h.source.end_line,
                "content_hash": h.source.content_hash,
            }
            for h in final_hits
        ],
        "chunks": [c.to_dict() for c in all_chunks],
        "claims": [c.to_dict() for c in claims],
        "discarded": discarded,
        "consolidated": consolidated,
        "retrieved": [h.to_dict() for h in final_hits],
        "hybrid": telemetry.to_dict(),
        "est_tokens_raw": raw_tokens,
        "est_tokens_compressed": max(1, count_tokens(consolidated)) if consolidated else 0,
        "est_tokens_semantic": telemetry.est_tokens_semantic,
        "reduction_pct": round(
            100
            * (
                1
                - (
                    len(consolidated)
                    / max(sum(len(str(d.get("text") or "")) for d in docs), 1)
                )
            ),
            1,
        )
        if docs
        else 0.0,
    }


def compress_documents_routed(
    docs: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Alias estável para handlers/rag_compress."""
    return compress_documents_hybrid(docs, **kwargs)


def main() -> None:
    p = argparse.ArgumentParser(description="Recuperação híbrida structured|flat")
    p.add_argument("file", type=Path, nargs="?", help="documento para classificar/recuperar")
    p.add_argument("--query", default="", help="query lexical/semântica")
    p.add_argument("--no-semantic", action="store_true")
    p.add_argument("--detect-only", action="store_true")
    args = p.parse_args()
    if not args.file:
        p.error("file obrigatório")
    text = args.file.read_text(encoding="utf-8")
    evidence = detect_structure(text)
    if args.detect_only:
        print(json.dumps(evidence.to_dict(), ensure_ascii=False, indent=2))
        return
    result = compress_documents_hybrid(
        [{"name": args.file.name, "text": text, "lines": text.count("\n") + 1}],
        query=args.query,
        enable_semantic=not args.no_semantic,
    )
    print(
        json.dumps(
            {
                "structure": evidence.to_dict(),
                "hybrid": result.get("hybrid"),
                "retrieved": result.get("retrieved"),
                "consolidated": result.get("consolidated"),
                "est_tokens_compressed": result.get("est_tokens_compressed"),
                "est_tokens_semantic": result.get("est_tokens_semantic"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
