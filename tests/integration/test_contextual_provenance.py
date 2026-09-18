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
    keys = {(c["context"], c["id"]) for c in prov["claims"]}
    assert len(keys) == len(prov["claims"])
    namespaces = {str(c.get("context") or "") for c in prov["claims"]}
    assert "ms-cliente" in namespaces
    assert "ms-pagamento" in namespaces
    for cid in ids:
        assert cid.startswith("CLM-")
        assert "ms-cliente" not in cid
        assert "ms-pagamento" not in cid
    assert "uid" not in prov["claims"][0]
    assert "local_id" not in prov["claims"][0]


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
    assert ids == ["CLM-0001", "CLM-0001"]
    beta = next(m for m in merged if m["text"] == "beta")
    alpha = next(m for m in merged if m["text"] == "alpha")
    assert alpha["context"] == "s1"
    assert beta["context"] == "s2"
    assert "uid" not in alpha
    assert "local_id" not in beta


def test_dedup_preserva_mesmo_conteudo_em_contextos_distintos():
    shared = {
        "id": "CLM-0001",
        "text": "alpha",
        "origin": "declared",
        "service_id": "shared",
        "chunk_id": "c1",
        "sources": [{"document": "a.yaml"}],
    }
    merged = merge_claims(
        [
            {**shared, "context": "ms-cliente"},
            {**shared, "context": "ms-pagamento"},
            {**shared, "id": "CLM-0002", "context": "ms-cliente"},
        ]
    )
    assert len(merged) == 2
    by_ctx = {m["context"]: m for m in merged}
    assert set(by_ctx) == {"ms-cliente", "ms-pagamento"}
    assert by_ctx["ms-cliente"]["id"] == "CLM-0001"
    assert by_ctx["ms-pagamento"]["id"] == "CLM-0001"


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
    synth = next(c for c in spec.claims if c.id.startswith("CLM-SYN-"))
    assert synth.id == "CLM-SYN-001"
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


def test_leitura_aceita_id_namespaced_e_devolve_o_publico():
    from src.domain.provenance import merge_claims, parse_claim_ref

    assert parse_claim_ref("CLM-0001") == ("CLM-0001", None)
    assert parse_claim_ref("CLM-R001") == ("CLM-R001", None)
    assert parse_claim_ref("CLM-low-0001") == ("CLM-low-0001", None)
    assert parse_claim_ref("CLM-Z") == ("CLM-Z", None)
    assert parse_claim_ref("CLM-ms-cliente-0001") == ("CLM-0001", "ms-cliente")
    assert parse_claim_ref("CLM-ms-cliente-R001") == ("CLM-R001", "ms-cliente")
    assert parse_claim_ref("CLM-ms-cliente-SYN-001") == ("CLM-SYN-001", "ms-cliente")
    assert parse_claim_ref("ms-cliente:CLM-0001") == ("CLM-0001", "ms-cliente")
    merged = merge_claims(
        [
            {
                "id": "CLM-ms-cliente-0001",
                "text": "alpha",
                "origin": "declared",
                "service_id": "ms-cliente",
                "sources": [],
            }
        ]
    )
    assert merged[0]["id"] == "CLM-0001"
    assert merged[0]["context"] == "ms-cliente"
    assert "uid" not in merged[0]


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


def test_id_repetido_sem_contexto_e_fail_closed():
    from src.domain.provenance import AmbiguousClaimRef, merge_claims, resolve_claim

    merged = merge_claims(
        [
            {
                "id": "CLM-0001",
                "text": "alpha",
                "origin": "declared",
                "service_id": "s1",
                "sources": [],
            },
            {
                "id": "CLM-0001",
                "text": "beta",
                "origin": "declared",
                "service_id": "s2",
                "sources": [],
            },
        ]
    )
    with pytest.raises(AmbiguousClaimRef):
        resolve_claim(merged, "CLM-0001")
    assert resolve_claim(merged, "CLM-0001", context="s1")["text"] == "alpha"
    assert resolve_claim(merged, "s2:CLM-0001")["text"] == "beta"


def test_events_tip_e_o_ultimo_hmac(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-tip-1",
    )
    run_dir = Path(result["run_dir"])
    rows = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert rows[-1]["event"] == "run_finished"
    assert manifest["integrity"]["events_tip"] == rows[-1]["hmac"]
    assert manifest["integrity"]["kid"] == "v1"
    assert verify_run_dir(run_dir)["ok"] is True


def test_rotacao_kid_verifica_run_antiga(tmp_path: Path, monkeypatch):
    antiga = "test-integrity-key-not-for-prod"
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="prov-kid-1",
    )
    run_dir = Path(result["run_dir"])
    monkeypatch.setenv("PROMPTLESS_INTEGRITY_KEY", "nova-chave-de-teste-xxxx")
    monkeypatch.setenv("PROMPTLESS_INTEGRITY_KID", "v2")
    monkeypatch.setenv("PROMPTLESS_INTEGRITY_KEYS", f"v1={antiga}")
    assert verify_run_dir(run_dir)["ok"] is True, verify_run_dir(run_dir)["errors"]
