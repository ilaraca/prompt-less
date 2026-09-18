"""IR → OpenAPI/Mermaid: golden, validação estrutural e anti-divergência."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.domain.spec import CanonicalSpec
from src.renderers import render_mermaid, render_openapi
from src.run import run
from src.spec.builder import build_canonical_spec
from src.validators import (
    validate_derived_artifact,
    validate_mermaid_against_spec,
    validate_openapi_against_spec,
    validate_openapi_document,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden"
ALIGNED_CASES = ("happy_path", "access_denied", "two_services")

_STATUS_RE = re.compile(r"(?<![-\w.])([1-5]\d{2})(?![\w.])")


def _spec_golden() -> CanonicalSpec:
    """Spec estável (sem RAG) usado pelos goldens dos dois renderizadores."""
    return build_canonical_spec(
        ui={
            "inputs": [
                {
                    "name": "nome",
                    "type": "string",
                    "required": True,
                    "type_origin": "declared",
                },
                {
                    "name": "cpf",
                    "type": "string",
                    "required": True,
                    "type_origin": "declared",
                },
            ],
            "columns": [
                {"name": "id", "type": "string", "type_origin": "inferred"},
                {"name": "status", "type": "string", "type_origin": "inferred"},
            ],
            "actions": [{"id": "salvar", "method": "POST", "path": "/clientes"}],
        },
        regras={
            "bloqueios": [
                {"trigger": "CPF inválido", "status": 400, "code": "CPF_INVALIDO"},
                {"trigger": "sem permissão admin", "status": 403},
            ],
            "decisoes": [
                {"quando": "payload válido", "entao": "persistir e retornar 201"}
            ],
        },
        claims=[
            {
                "id": "CLM-1",
                "text": "CPF inválido devolve 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml", "section": "bloqueios[0]"}],
            }
        ],
        servico={"id": "ms-cliente", "nome": "Cadastro de Cliente", "repos": ["bff-cliente"]},
    )


def _spec_unresolved() -> CanonicalSpec:
    """Ação sem método/path e sem 2xx declarado — tudo deve ficar unresolved."""
    return build_canonical_spec(
        ui={
            "inputs": [{"name": "cpf", "type": "string", "type_origin": "declared"}],
            "columns": [],
            "actions": [{"id": "enviar"}],
        },
        regras={
            "bloqueios": [{"trigger": "CPF inválido", "status": 400}],
            "decisoes": ["revisar manualmente"],
        },
        claims=[
            {
                "id": "CLM-1",
                "text": "CPF inválido devolve 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
    )


def _run_case(case_id: str, tipo: str, tmp_path: Path) -> dict[str, Any]:
    result = run(
        tipo,
        dry_run=True,
        inputs_dir=FIXTURES / case_id,
        output_root=tmp_path / f"{case_id}-{tipo}",
        run_id=f"derived-{case_id}-{tipo}",
        no_split=True,
    )
    assert result["status"] == "completed", result.get("validation")
    return result


def test_run_openapi_e_mermaid_usam_o_ir(tmp_path: Path):
    """`run openapi|mermaid` deriva do Canonical Spec, não do scaffold legado."""
    openapi = _run_case("happy_path", "openapi", tmp_path)
    mermaid = _run_case("happy_path", "mermaid", tmp_path)

    assert openapi["canonical_spec"], "run deve persistir o IR usado"
    texto_openapi = Path(openapi["output"]).read_text(encoding="utf-8")
    texto_mermaid = Path(mermaid["output"]).read_text(encoding="utf-8")

    assert "DRY-RUN MARKERS" not in texto_openapi
    assert "Canonical Spec" in texto_openapi
    doc = yaml.safe_load(texto_openapi)
    assert doc["info"]["x-service-id"] == "default"
    assert doc["paths"]["/clientes"]["post"]["x-operation-id"] == "OP-001"

    assert "{{happy_path}}" not in texto_mermaid
    assert "POST /clientes" in texto_mermaid


def test_openapi_gerado_passa_validacao_estrutural(tmp_path: Path):
    for case_id in ALIGNED_CASES:
        result = _run_case(case_id, "openapi", tmp_path)
        doc = yaml.safe_load(Path(result["output"]).read_text(encoding="utf-8"))
        validation = validate_openapi_document(doc)
        assert not validation.has_errors, validation.to_dict()


def test_golden_openapi():
    esperado = (GOLDEN / "openapi.yaml").read_text(encoding="utf-8")
    assert render_openapi(_spec_golden()) == esperado


def test_golden_mermaid():
    esperado = (GOLDEN / "sequence.mmd").read_text(encoding="utf-8")
    assert render_mermaid(_spec_golden()) == esperado


def test_renderizadores_sao_deterministicos():
    spec = _spec_golden()
    assert render_openapi(spec) == render_openapi(_spec_golden())
    assert render_mermaid(spec) == render_mermaid(_spec_golden())


@pytest.mark.parametrize("case_id", ALIGNED_CASES)
def test_sem_divergencia_entre_ir_historia_prd_openapi_mermaid(
    case_id: str, tmp_path: Path
):
    """Golden de coerência: os cinco artefatos falam do mesmo IR."""
    historia = _run_case(case_id, "historia", tmp_path)
    openapi = _run_case(case_id, "openapi", tmp_path)
    mermaid = _run_case(case_id, "mermaid", tmp_path)

    # o IR precisa ser idêntico nas três execuções (mesma autoridade semântica)
    especificacoes = {
        tipo: Path(r["canonical_spec"]).read_text(encoding="utf-8")
        for tipo, r in (
            ("historia", historia),
            ("openapi", openapi),
            ("mermaid", mermaid),
        )
    }
    assert len(set(especificacoes.values())) == 1, "IR divergente entre execuções"

    ir = yaml.safe_load(especificacoes["historia"])
    texto_historia = Path(historia["outputs"]["historia"]).read_text(encoding="utf-8")
    texto_prd = Path(historia["outputs"]["prd"]).read_text(encoding="utf-8")
    texto_openapi = Path(openapi["output"]).read_text(encoding="utf-8")
    texto_mermaid = Path(mermaid["output"]).read_text(encoding="utf-8")
    doc = yaml.safe_load(texto_openapi)

    # RF/AC do IR aparecem em história e PRD
    for ac in ir["acceptance_criteria"]:
        assert ac["id"] in texto_historia
        assert ac["id"] in texto_prd
    for rf in ir["requirements"]:
        assert rf["id"] in texto_prd

    # erros do IR aparecem nos quatro artefatos derivados
    for err in ir["errors"]:
        status = str(err["status"])
        assert status in texto_prd
        assert status in texto_mermaid
        assert status in doc["paths"][ir["operations"][0]["path"]][
            ir["operations"][0]["method"].lower()
        ]["responses"]

    # paths e métodos do IR são exatamente os do OpenAPI e da sequência
    ir_paths = {op["path"] for op in ir["operations"] if op["path"]}
    assert set(doc["paths"]) == ir_paths
    for op in ir["operations"]:
        assert op["method"].lower() in doc["paths"][op["path"]]
        assert f"{op['method']} {op['path']}" in texto_mermaid
        assert op["path"] in texto_prd

    # nenhum status fora do IR em OpenAPI ou Mermaid
    ir_statuses = {int(e["status"]) for e in ir["errors"]}
    for op in ir["operations"]:
        sucesso = op["success_status"]
        if sucesso.get("value") is not None and not sucesso.get("requires_review"):
            ir_statuses.add(int(sucesso["value"]))
    assert {int(s) for s in _STATUS_RE.findall(texto_mermaid)} <= ir_statuses

    spec_obj = _build_from_fixture(case_id)
    assert not validate_openapi_against_spec(spec_obj, doc).has_errors
    assert not validate_mermaid_against_spec(spec_obj, texto_mermaid).has_errors


def _build_from_fixture(case_id: str) -> CanonicalSpec:
    """Reconstrói o IR do fixture sem RAG (só UI + regras declaradas)."""
    from src.ingest import load_inputs
    from src.preprocess import preprocess

    slim = preprocess(load_inputs("openapi", inputs_dir=FIXTURES / case_id))
    return build_canonical_spec(
        ui=slim["ui"],
        regras=slim["regras"],
        engenharia=slim["engenharia"],
        claims=[],
    )


def test_divergencia_injetada_e_detectada():
    """O golden gate falha quando o artefato inventa status, path ou campo."""
    spec = _spec_golden()
    doc = yaml.safe_load(render_openapi(spec))
    operacao = doc["paths"]["/clientes"]["post"]

    status_inventado = yaml.safe_load(yaml.safe_dump(doc))
    status_inventado["paths"]["/clientes"]["post"]["responses"]["418"] = {
        "description": "chá"
    }
    codigos = {
        i.code
        for i in validate_openapi_against_spec(spec, status_inventado).errors
    }
    assert "ARTIFACT_STATUS_NOT_IN_IR" in codigos

    sucesso_inventado = yaml.safe_load(yaml.safe_dump(doc))
    sucesso_inventado["paths"]["/clientes"]["post"]["responses"]["200"] = {
        "description": "ok"
    }
    codigos = {
        i.code
        for i in validate_openapi_against_spec(spec, sucesso_inventado).errors
    }
    assert "ARTIFACT_RESOLVED_WITHOUT_EVIDENCE" in codigos

    path_inventado = yaml.safe_load(yaml.safe_dump(doc))
    path_inventado["paths"]["/clientes/lote"] = {"post": dict(operacao)}
    codigos = {i.code for i in validate_openapi_against_spec(spec, path_inventado).errors}
    assert "ARTIFACT_PATH_NOT_IN_IR" in codigos
    assert "ARTIFACT_OPERATION_NOT_IN_IR" in codigos

    campo_inventado = yaml.safe_load(yaml.safe_dump(doc))
    campo_inventado["components"]["schemas"]["SalvarRequest"]["properties"][
        "score_interno"
    ] = {"type": "number"}
    codigos = {i.code for i in validate_openapi_against_spec(spec, campo_inventado).errors}
    assert "ARTIFACT_FIELD_NOT_IN_IR" in codigos

    mermaid = render_mermaid(spec).replace("400 CPF_INVALIDO", "418 CPF_INVALIDO")
    codigos = {i.code for i in validate_mermaid_against_spec(spec, mermaid).errors}
    assert "ARTIFACT_STATUS_NOT_IN_IR" in codigos

    mermaid = render_mermaid(spec).replace("POST /clientes", "POST /clientes/lote")
    codigos = {i.code for i in validate_mermaid_against_spec(spec, mermaid).errors}
    assert "ARTIFACT_PATH_NOT_IN_IR" in codigos


def test_unresolved_nunca_aparece_resolvido():
    spec = _spec_unresolved()
    op = spec.operations[0]
    assert op.unresolved == ["method", "path", "success_status"]
    assert op.resolved_success_status() is None

    doc = yaml.safe_load(render_openapi(spec))
    assert doc["paths"] == {}
    pendentes = doc["x-unresolved-operations"]
    assert pendentes[0]["id"] == "OP-001"
    assert pendentes[0]["unresolved"] == ["method", "path", "success_status"]
    assert not validate_openapi_document(doc).has_errors
    assert not validate_openapi_against_spec(spec, doc).has_errors

    sequencia = render_mermaid(spec)
    assert "unresolved: method, path, success_status" in sequencia
    assert not validate_mermaid_against_spec(spec, sequencia).has_errors

    # pergunta aberta não bloqueante registra o que falta para revisão humana
    perguntas = [q for q in spec.open_questions if not q.blocking]
    assert {q.text for q in perguntas} and all("OP-001" in q.text for q in perguntas)


def test_sucesso_sem_evidencia_nao_vira_200():
    spec = _spec_unresolved()
    doc = yaml.safe_load(render_openapi(spec))
    assert "200" not in yaml.safe_dump(doc)
    assert "201" not in render_mermaid(spec)


def test_sucesso_com_evidencia_unica_e_resolvido():
    spec = _spec_golden()
    op = spec.operations[0]
    status = op.success_status
    assert op.resolved_success_status() == 201
    assert status.origin == "declared"
    assert status.source_claims, "status resolvido precisa de claim de origem"


def test_gate_bloqueia_artefato_divergente(tmp_path: Path, monkeypatch):
    """Renderizador que inventa status não emite artefato (fail-closed)."""
    import src.run as run_module

    original = run_module.render_openapi

    def _render_com_status_inventado(spec, template=None):
        return original(spec, template).replace("'400':", "'418':", 1)

    monkeypatch.setattr(run_module, "render_openapi", _render_com_status_inventado)
    result = run(
        "openapi",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path / "gate",
        run_id="derived-gate",
        no_split=True,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "derived_artifact_divergence"
    relatorio = Path(result["report"])
    assert relatorio.is_file()
    assert "ARTIFACT_STATUS_NOT_IN_IR" in relatorio.read_text(encoding="utf-8")
    assert not list((tmp_path / "gate").rglob("openapi.yaml"))


def test_validate_derived_artifact_aceita_artefato_do_ir():
    spec = _spec_golden()
    assert not validate_derived_artifact("openapi", render_openapi(spec), spec).has_errors
    assert not validate_derived_artifact("mermaid", render_mermaid(spec), spec).has_errors
    assert not validate_derived_artifact("historia", "qualquer", spec).issues
