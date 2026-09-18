"""Proveniência contextual: namespace, fingerprint, cadeia de hash, revisão."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.provenance import claim_fingerprint, merge_claims
from src.run import run
from src.runtime import verify_run_dir
from src.spec.builder import build_canonical_spec
from src.validators import validate_spec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_multi_contexto_nao_perde_claims(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        all_contexts=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path,
        run_id="prov-multi-1",
    )
    assert result["status"] == "completed"
    assert result["split"] is True
    by_ctx = result["by_context"]
    assert len(by_ctx) >= 2

    gathered: list[dict] = []
    for ctx in by_ctx:
        claims = list(ctx.get("claims") or [])
        assert claims, f"contexto {ctx.get('context')} sem claims"
        gathered.extend(claims)

    merged = merge_claims(gathered)
    prov = json.loads(Path(result["provenance"]).read_text(encoding="utf-8"))
    prov_fps = {claim_fingerprint(c) for c in prov["claims"]}
    expected_fps = {claim_fingerprint(c) for c in merged}
    assert expected_fps <= prov_fps
    assert len(prov["claims"]) == len(merged)
    assert prov["claims_count"] == len(merged)
    assert len(prov["claims"]) > 2, "regressão: dedup por id colidia entre contextos"

    ids = [c["id"] for c in prov["claims"]]
    assert len(ids) == len(set(ids))
    namespaces = {
        str(c.get("context") or c.get("service_id") or "") for c in prov["claims"]
    }
    assert "ms-cliente" in namespaces
    assert "ms-pagamento" in namespaces
    for cid in ids:
        assert cid.startswith("CLM-")
        assert "ms-cliente" in cid or "ms-pagamento" in cid or "default" in cid


def test_dedup_por_identidade_completa_preserva_colisao_de_id():
    a = {
        "id": "CLM-0001",
        "text": "alpha",
        "origin": "declared",
        "service_id": "s1",
        "chunk_id": "c1",
        "sources": [{"document": "a.yaml"}],
    }
    b = {
        "id": "CLM-0001",
        "text": "beta",
        "origin": "declared",
        "service_id": "s2",
        "chunk_id": "c2",
        "sources": [{"document": "b.yaml"}],
    }
    duplicate = {
        "id": "CLM-0002",
        "text": "alpha",
        "origin": "declared",
        "service_id": "s1",
        "chunk_id": "c1",
        "sources": [{"document": "a.yaml"}],
    }
    merged = merge_claims([a, b, duplicate])
    assert len(merged) == 2
    ids = [m["id"] for m in merged]
    assert len(set(ids)) == 2
    assert "CLM-0001" in ids
    renamed = next(m for m in merged if m["text"] == "beta")
    assert renamed["id"] != "CLM-0001"
    assert renamed["local_id"] == "CLM-0001"
    assert renamed["context"] == "s2"
    kept = next(m for m in merged if m["text"] == "alpha")
    assert kept["id"] == "CLM-0001"


def test_adulteracao_de_evento_e_detectada(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-tamper-evt",
    )
    run_dir = Path(result["run_dir"])
    clean = verify_run_dir(run_dir)
    assert clean["ok"] is True, clean["errors"]

    events = run_dir / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["event"] = "tampered"
    lines[0] = json.dumps(rec, ensure_ascii=False)
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = verify_run_dir(run_dir)
    assert out["ok"] is False
    assert out["errors"]


def test_adulteracao_de_artefato_e_detectada(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-tamper-art",
    )
    run_dir = Path(result["run_dir"])
    assert verify_run_dir(run_dir)["ok"] is True
    art = next((run_dir / "artifacts").rglob("historia.md"))
    art.write_text(art.read_text(encoding="utf-8") + "\n# pwned\n", encoding="utf-8")
    out = verify_run_dir(run_dir)
    assert out["ok"] is False
    assert any("adulterado" in e for e in out["errors"])


def test_match_baixa_confianca_exige_revisao_sem_mudar_status():
    spec = build_canonical_spec(
        ui={},
        regras={"bloqueios": [{"trigger": "alpha bravo charlie", "status": 400}]},
        claims=[
            {
                "id": "CLM-low-0001",
                "text": "alpha bravo charlie delta echo foxtrot",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "t.yaml"}],
            }
        ],
    )
    rf = spec.requirements[0]
    assert rf.status == "draft"
    assert rf.claim_links
    link = rf.claim_links[0]
    assert link.claim_id == "CLM-low-0001"
    assert link.method == "lexical"
    assert link.score == 0.5
    assert link.requires_review is True
    validation = validate_spec(spec)
    assert validation.has_errors is False
    assert validation.to_dict()["status"] == "passed"
    assert any(i.code == "LOW_CONFIDENCE_CLAIM_MATCH" for i in validation.warnings)


def test_claim_sintetico_ganha_hash_secao_e_locator():
    spec = build_canonical_spec(
        ui={},
        regras={"bloqueios": [{"trigger": "xyzzy-unico-sem-match", "status": 400}]},
        claims=[],
        servico={"id": "ms-demo"},
    )
    synth = next(c for c in spec.claims if "-SYN-" in c.id)
    assert synth.id.startswith("CLM-ms-demo-")
    assert synth.sources
    src = synth.sources[0]
    assert src.content_hash
    assert src.section == "bloqueios[0]"
    assert src.locator == "$.bloqueios[0]"
    assert src.start_line is None


def test_artefatos_listam_claims_utilizados(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-art-1",
    )
    assert result["status"] == "completed"
    historias = list(tmp_path.rglob("historia.md"))
    prds = list(tmp_path.rglob("PRD.md"))
    assert historias and prds
    for path in (historias[0], prds[0]):
        text = path.read_text(encoding="utf-8")
        assert "## Proveniência" in text or "## 16. Proveniência" in text
    assert "CLM-" in text


def test_emit_sem_chave_e_fail_closed(tmp_path: Path, monkeypatch):
    from src.runtime.event_store import EventStore
    from src.runtime.integrity import MissingIntegrityKey

    monkeypatch.delenv("PROMPTLESS_INTEGRITY_KEY", raising=False)
    store = EventStore(tmp_path / "events.jsonl")
    with pytest.raises(MissingIntegrityKey):
        store.emit("run_started", run_id="x")


def test_evento_forjado_com_prev_hash_correto_falha_hmac(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-forged-hmac",
    )
    run_dir = Path(result["run_dir"])
    assert verify_run_dir(run_dir)["ok"] is True
    events = run_dir / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    forged = {
        "event": "forged",
        "timestamp": last["timestamp"],
        "prev_hash": last["hash"],
        "prev_hmac": last["hmac"],
        "hash": "0" * 64,
        "hmac": "0" * 64,
    }
    events.write_text(
        "\n".join(lines + [json.dumps(forged, ensure_ascii=False)]) + "\n",
        encoding="utf-8",
    )
    out = verify_run_dir(run_dir)
    assert out["ok"] is False
    assert any("hmac" in e for e in out["errors"])


def test_verify_com_chave_errada_falha(tmp_path: Path, monkeypatch):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-wrong-key",
    )
    run_dir = Path(result["run_dir"])
    assert verify_run_dir(run_dir)["ok"] is True
    monkeypatch.setenv("PROMPTLESS_INTEGRITY_KEY", "outra-chave-de-teste-xx")
    out = verify_run_dir(run_dir)
    assert out["ok"] is False
    assert any("hmac" in e.lower() for e in out["errors"])
