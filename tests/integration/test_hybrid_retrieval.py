"""Golden + unit: recuperação híbrida structured|flat + camada semântica local."""
from __future__ import annotations

from pathlib import Path

import yaml

from src.doc_compress import SIGNAL_RE, compress_documents
from src.hybrid_retrieval import (
    build_query_from_ctx,
    compress_documents_hybrid,
    dedupe_hits,
    detect_structure,
    scrub_sensitive,
    RetrievedHit,
)
from src.domain.source_ref import SourceRef

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXPECTED = FIXTURES / "hybrid" / "expected_retrieval.yaml"


def _load_expected() -> dict:
    return yaml.safe_load(EXPECTED.read_text(encoding="utf-8")) or {}


def test_detect_structure_structured_vs_flat():
    structured = (FIXTURES / "hybrid_structured" / "spec.md").read_text(encoding="utf-8")
    flat = (FIXTURES / "hybrid_synonym" / "spec.txt").read_text(encoding="utf-8")
    s = detect_structure(structured)
    f = detect_structure(flat)
    assert s.kind == "structured"
    assert s.heading_count >= 2
    assert f.kind == "flat"
    assert f.heading_count < 2
    assert "heading_count" in s.reason


def test_structured_uses_anchors_with_source_ref_and_score(tmp_path: Path):
    text = (FIXTURES / "hybrid_structured" / "spec.md").read_text(encoding="utf-8")
    regras = yaml.safe_load((FIXTURES / "hybrid_structured" / "regras.yaml").read_text())
    query = build_query_from_ctx({"regras": regras, "ui": {"actions": [{"method": "POST", "path": "/clientes"}]}})
    result = compress_documents_hybrid(
        [{"name": "spec.md", "text": text}],
        query=query,
        state_dir=tmp_path / "state",
        enable_semantic=False,
    )
    hybrid = result["hybrid"]
    assert hybrid["structure"][0]["kind"] == "structured"
    assert "structural_anchor" in hybrid["strategies_used"]
    index = tmp_path / "state" / "doc_section_index.json"
    assert index.exists()
    import json
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert "spec.md" in payload["documents"]
    assert payload["documents"]["spec.md"]["inverted"]
    # índice não deve parecer prompt payload
    assert "não incluir no prompt" in payload.get("note", "") or "nao" in str(payload.get("note", "")).lower()

    retrieved = result["retrieved"]
    assert retrieved
    for hit in retrieved:
        assert hit["source"]["document"] == "spec.md"
        assert "score" in hit and hit["score"] > 0
        assert hit["strategy"] == "structural_anchor"
    blob = " ".join(h["text"] for h in retrieved)
    for needle in ("400", "CPF", "401"):
        assert needle.lower() in blob.lower() or needle in blob


def test_flat_keeps_doc_compress_path_no_regression():
    """Insumo flat com SIGNAL_RE: híbrido ≥ lexical puro nos sinais críticos."""
    # trecho da amostra com sinais conhecidos
    text = "\n".join(
        [f"ruido de telemetria processo={i}" for i in range(1, 100)]
        + [
            "regra: CPF inválido retorna erro HTTP 400",
            "endpoint POST /clientes exige auth",
            "permissão negada responde status 403",
        ]
        + [f"ruido de telemetria processo={i}" for i in range(101, 140)]
    )
    docs = [{"name": "flat.txt", "text": text}]
    baseline = compress_documents(docs, consolidated_chars=800)
    hybrid = compress_documents_hybrid(
        docs,
        query="CPF bloqueio auth permiss 400 403",
        enable_semantic=False,
        consolidated_chars=800,
    )
    assert hybrid["hybrid"]["structure"][0]["kind"] == "flat"
    assert "lexical_flat" in hybrid["hybrid"]["strategies_used"]
    base_blob = " ".join(baseline.get("chunk_summaries") or []).lower()
    hyb_blob = " ".join(hybrid.get("chunk_summaries") or []).lower()
    for needle in ("cpf", "400"):
        assert needle in base_blob
        assert needle in hyb_blob


def test_semantic_recovers_synonym_without_external_provider(tmp_path: Path):
    text = (FIXTURES / "hybrid_synonym" / "spec.txt").read_text(encoding="utf-8")
    # confirma ausência de SIGNAL_RE nas linhas úteis
    useful = [ln for ln in text.splitlines() if "documento" in ln.lower() or "autenticacao" in ln.lower()]
    assert useful
    assert not any(SIGNAL_RE.search(ln) for ln in useful)

    regras = yaml.safe_load((FIXTURES / "hybrid_synonym" / "regras.yaml").read_text())
    query = build_query_from_ctx({"regras": regras})
    lexical_only = compress_documents_hybrid(
        [{"name": "spec.txt", "text": text}],
        query=query,
        enable_semantic=False,
        state_dir=tmp_path / "state-lex",
    )
    with_semantic = compress_documents_hybrid(
        [{"name": "spec.txt", "text": text}],
        query=query,
        enable_semantic=True,
        state_dir=tmp_path / "state-sem",
    )
    sem_blob = " ".join(h["text"] for h in with_semantic["retrieved"]).lower()
    assert "documento" in sem_blob or "identificacao" in sem_blob
    assert with_semantic["hybrid"]["semantic_provider"] == "local"
    assert with_semantic["hybrid"]["semantic_hits"] >= 1
    assert with_semantic.get("est_tokens_semantic", 0) >= 0
    # recall sobe vs lexical puro neste fixture
    lex_blob = " ".join(h["text"] for h in lexical_only["retrieved"]).lower()
    lex_hit = "documento" in lex_blob or "identificacao" in lex_blob
    sem_hit = "documento" in sem_blob or "identificacao" in sem_blob
    assert sem_hit
    assert sem_hit >= lex_hit


def test_narrative_fixture_recall_via_semantic(tmp_path: Path):
    text = (FIXTURES / "hybrid_narrative" / "spec.txt").read_text(encoding="utf-8")
    regras = yaml.safe_load((FIXTURES / "hybrid_narrative" / "regras.yaml").read_text())
    query = build_query_from_ctx({"regras": regras})
    result = compress_documents_hybrid(
        [{"name": "spec.txt", "text": text}],
        query=query,
        enable_semantic=True,
        state_dir=tmp_path / "state",
        consolidated_chars=600,
    )
    blob = " ".join(h["text"] for h in result["retrieved"]).lower()
    assert "recusa" in blob or "sessao" in blob or "barrada" in blob
    # narrativa sem SIGNAL_RE: lexical descarta; semântica local recupera
    assert result["hybrid"]["semantic_provider"] == "local"
    assert (
        any(h["strategy"] == "semantic_local" for h in result["retrieved"])
        or result["hybrid"]["semantic_hits"] >= 1
        or "recusa" in blob
    )
    for h in result["retrieved"]:
        assert h["source"].get("document")
        assert h["score"] > 0


def test_scrub_removes_secrets_before_semantic():
    dirty = "chave api_key=ABCDEFGHIJKLMNOPQRSTUVWX e CPF 123.456.789-00 no texto"
    clean, n = scrub_sensitive(dirty)
    assert n >= 2
    assert "ABCDEFGHIJKLMNOPQRSTUVWX" not in clean
    assert "123.456.789-00" not in clean
    assert "REDACTED" in clean


def test_dedupe_preserves_source_diversity():
    hits = [
        RetrievedHit(
            text="alpha",
            source=SourceRef(document="a.txt", content_hash="sha256:1"),
            score=1.0,
            strategy="lexical_flat",
            document="a.txt",
        ),
        RetrievedHit(
            text="beta",
            source=SourceRef(document="b.txt", content_hash="sha256:2"),
            score=0.9,
            strategy="lexical_flat",
            document="b.txt",
        ),
        RetrievedHit(
            text="alpha2",
            source=SourceRef(document="a.txt", content_hash="sha256:3"),
            score=0.8,
            strategy="lexical_flat",
            document="a.txt",
        ),
        RetrievedHit(
            text="alpha",  # dup texto
            source=SourceRef(document="c.txt", content_hash="sha256:4"),
            score=0.7,
            strategy="semantic_local",
            document="c.txt",
        ),
    ]
    out = dedupe_hits(hits)
    docs = [h.document for h in out]
    assert docs[0] == "a.txt"
    assert "b.txt" in docs
    # texto duplicado "alpha" de c.txt some
    assert not any(h.document == "c.txt" for h in out)


def test_golden_hybrid_expected_file():
    spec = _load_expected()
    assert "structured" in (spec.get("cases") or {})
    assert "synonym" in (spec.get("cases") or {})
    assert "narrative" in (spec.get("cases") or {})


def test_budget_respected_with_semantic(tmp_path: Path):
    text = (FIXTURES / "hybrid_structured" / "spec.md").read_text(encoding="utf-8")
    result = compress_documents_hybrid(
        [{"name": "spec.md", "text": text}],
        query="CPF auth 400 401",
        enable_semantic=True,
        consolidated_chars=120,
        semantic_budget_chars=40,
        state_dir=tmp_path / "state",
    )
    assert len(result["consolidated"]) <= 120 + 1  # clip may add …
    assert result["hybrid"]["semantic_chars_used"] <= 40
