"""Provenance: claims apontam para fonte; descarte é reportado."""
from __future__ import annotations

import json
from pathlib import Path

from src.doc_compress import compress_documents, summarize_document_chunk, build_document_chunks
from src.domain import ClaimOrigin
from src.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_claim_has_source_ref():
    docs = [
        {
            "name": "regras.txt",
            "text": "ruido telemetria cpu=1\nREGRA bloqueio — sem permissão retornar HTTP 403\nmais ruido",
            "lines": 3,
            "est_tokens_raw": 20,
        }
    ]
    result = compress_documents(docs, consolidated_chars=400)
    assert result["claims"], "deve extrair pelo menos um claim com sinal"
    claim = result["claims"][0]
    assert claim["origin"] == ClaimOrigin.DECLARED.value
    assert claim["sources"], "todo claim precisa de SourceRef"
    src = claim["sources"][0]
    assert src["document"] == "regras.txt"
    assert src.get("content_hash")
    assert src.get("start_line") is not None


def test_noise_chunk_is_discarded():
    docs = [
        {
            "name": "noise.txt",
            "text": "\n".join([f"L{i}: ruido telemetria cpu={i}%" for i in range(40)]),
            "lines": 40,
            "est_tokens_raw": 200,
        }
    ]
    result = compress_documents(docs)
    assert result["discarded"], "chunks sem sinal devem aparecer em discarded"
    assert all(d.get("reason") == "no_known_signal" for d in result["discarded"])
    assert result["claims"] == []


def test_budget_omission_is_reported():
    # vários chunks com sinal; budget minúsculo força omissão
    blocks = []
    for i in range(8):
        blocks.append(f"## Seção {i}\nREGRA bloqueio endpoint HTTP 400 caso {i} auth permiss path /x{i}")
        blocks.append("\n".join([f"padding line {j}" for j in range(35)]))
    docs = [{"name": "big.txt", "text": "\n".join(blocks), "lines": 400, "est_tokens_raw": 2000}]
    result = compress_documents(docs, lines_per_chunk=40, consolidated_chars=80)
    budget_drops = [d for d in result["discarded"] if d.get("reason") == "budget_exceeded"]
    assert budget_drops, "descarte por budget deve ser reportado"


def test_run_writes_provenance_file(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-0001",
    )
    prov = Path(result["provenance"])
    assert prov.is_file()
    data = json.loads(prov.read_text(encoding="utf-8"))
    assert data["claims_count"] >= 1
    for claim in data["claims"]:
        assert claim.get("sources"), f"claim sem fonte: {claim.get('id')}"
    assert "discarded" in data


def test_chunk_summary_preserves_line_range():
    chunks = build_document_chunks(
        {
            "name": "spec.txt",
            "text": "intro\nREGRA HTTP 401 sem autenticação\nfim",
        },
        lines_per_chunk=40,
    )
    assert len(chunks) == 1
    summary = summarize_document_chunk(chunks[0])
    assert not summary.discarded
    assert summary.selected_lines
    assert chunks[0].start_line <= summary.selected_lines[0] <= chunks[0].end_line
