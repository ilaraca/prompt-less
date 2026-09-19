"""IR → OpenAPI/Mermaid: golden, validação estrutural e anti-divergência."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.domain.spec import CanonicalSpec
from src.renderers import render_mermaid, render_openapi
from src.runtime.run import run
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

    # erros ancorados no IR aparecem nos artefatos da operação dona;
    # órfãos ficam unresolved (PRD) e não são copiados para path/sequência
    referenced_errors = {
        eid
        for op in ir["operations"]
        for eid in (op.get("error_ids") or [])
    }
    contract_ops = [
        op
        for op in ir["operations"]
        if op.get("owner")
        and op.get("path")
        and op.get("method")
        and "owner" not in (op.get("unresolved") or [])
    ]
    for err in ir["errors"]:
        status = str(err["status"])
        assert status in texto_prd
        if err["id"] not in referenced_errors:
            continue
        assert status in texto_mermaid
        donas = [
            op
            for op in contract_ops
            if err["id"] in (op.get("error_ids") or [])
        ]
        assert donas, f"{err['id']} referenciado sem operação de contrato"
        for op in donas:
            assert status in doc["paths"][op["path"]][op["method"].lower()]["responses"]

    # paths e métodos do IR (contrato) são exatamente os do OpenAPI e da sequência
    ir_paths = {op["path"] for op in contract_ops}
    assert set(doc["paths"]) == ir_paths
    for op in contract_ops:
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
    """Reconstrói o IR do fixture sem RAG (só UI + regras + mapa)."""
    from src.ingest import load_inputs
    from src.preprocess import preprocess
    from src.repos.servicos import load_mapa

    slim = preprocess(load_inputs("openapi", inputs_dir=FIXTURES / case_id))
    mapa = load_mapa(FIXTURES / case_id / "mapa-servicos.yaml")
    return build_canonical_spec(
        ui=slim["ui"],
        regras=slim["regras"],
        engenharia=slim["engenharia"],
        claims=[],
        mapa=mapa,
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
    import src.runtime.handlers as handlers

    original = handlers.render_openapi

    def _render_com_status_inventado(spec, template=None):
        return original(spec, template).replace("'400':", "'418':", 1)

    monkeypatch.setattr(handlers, "render_openapi", _render_com_status_inventado)
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


def _two_services_pack() -> tuple[dict[str, Any], dict[str, Any]]:
    from src.ingest import load_inputs
    from src.preprocess import preprocess
    from src.repos.servicos import load_mapa

    slim = preprocess(load_inputs("openapi", inputs_dir=FIXTURES / "two_services"))
    mapa = load_mapa(FIXTURES / "two_services" / "mapa-servicos.yaml")
    assert mapa
    return slim, mapa


def test_operation_owner_preenchido_na_montagem_do_ir():
    slim, mapa = _two_services_pack()
    spec = build_canonical_spec(
        ui=slim["ui"],
        regras=slim["regras"],
        engenharia=slim["engenharia"],
        mapa=mapa,
    )
    by_name = {op.name: op for op in spec.operations}
    assert by_name["cadastrar"].owner == "ms-cliente"
    assert by_name["pagar"].owner == "ms-pagamento"
    assert all(op.owner for op in spec.contract_operations())


def test_context_contem_so_operacoes_do_servico():
    slim, mapa = _two_services_pack()
    from src.repos.servicos import get_service

    cliente = build_canonical_spec(
        ui=slim["ui"],
        regras=slim["regras"],
        mapa=mapa,
        servico=get_service(mapa, "ms-cliente"),
    )
    pagamento = build_canonical_spec(
        ui=slim["ui"],
        regras=slim["regras"],
        mapa=mapa,
        servico=get_service(mapa, "ms-pagamento"),
    )

    assert {op.name for op in cliente.operations} == {"cadastrar"}
    assert {op.owner for op in cliente.operations} == {"ms-cliente"}
    assert {op.name for op in pagamento.operations} == {"pagar"}
    assert {op.owner for op in pagamento.operations} == {"ms-pagamento"}
    assert {op.path for op in cliente.contract_operations()} == {"/clientes"}
    assert {op.path for op in pagamento.contract_operations()} == {"/pagamentos"}


def test_erros_seguem_a_operacao_dona_orfaos_nao_sao_copiados():
    slim, mapa = _two_services_pack()
    spec = build_canonical_spec(
        ui=slim["ui"], regras=slim["regras"], mapa=mapa
    )
    by_name = {op.name: op for op in spec.operations}
    erros = spec.errors_by_id()

    cpf = next(e for e in spec.errors if "cpf" in e.trigger.lower())
    saldo = next(e for e in spec.errors if "saldo" in e.trigger.lower())
    auth = next(e for e in spec.errors if "autent" in e.trigger.lower())

    assert cpf.id in by_name["cadastrar"].error_ids
    assert cpf.id not in by_name["pagar"].error_ids
    assert saldo.id in by_name["pagar"].error_ids
    assert saldo.id not in by_name["cadastrar"].error_ids
    assert auth.id not in by_name["cadastrar"].error_ids
    assert auth.id not in by_name["pagar"].error_ids
    assert erros[auth.id].status == 401

    perguntas = " ".join(q.text for q in spec.open_questions)
    assert auth.id in perguntas
    assert "unresolved" in perguntas

    doc = yaml.safe_load(render_openapi(spec))
    cliente_resp = doc["paths"]["/clientes"]["post"]["responses"]
    pag_resp = doc["paths"]["/pagamentos"]["post"]["responses"]
    assert "400" in cliente_resp and "422" not in cliente_resp
    assert "422" in pag_resp and "400" not in pag_resp
    assert "401" not in cliente_resp and "401" not in pag_resp

    sequencia = render_mermaid(spec)
    assert "/pagamentos" in sequencia and "/clientes" in sequencia
    assert "401" not in sequencia


def test_operacao_sem_dono_nao_e_emitida_como_resolvida():
    spec = build_canonical_spec(
        ui={
            "actions": [
                {"id": "misterio", "method": "POST", "path": "/desconhecido"}
            ]
        },
        regras={"bloqueios": [{"trigger": "x", "status": 400}]},
        mapa={
            "servicos": {
                "ms-cliente": {"keywords": ["cliente", "/clientes"]},
                "ms-pagamento": {"keywords": ["pagamento", "/pagamentos"]},
            }
        },
        servico={"id": "ms-cliente", "keywords": ["cliente"]},
    )
    assert spec.operations
    op = spec.operations[0]
    assert op.owner is None
    assert "owner" in op.unresolved
    assert not op.is_contract()
    assert spec.contract_operations() == []

    doc = yaml.safe_load(render_openapi(spec))
    assert doc["paths"] == {}
    assert doc["x-unresolved-operations"][0]["id"] == op.id
    assert "owner" in doc["x-unresolved-operations"][0]["unresolved"]

    sequencia = render_mermaid(spec)
    assert "unresolved: owner" in sequencia
    assert "/desconhecido" not in sequencia


def _openapi_doc(result: dict[str, Any]) -> dict[str, Any]:
    return yaml.safe_load(Path(result["output"]).read_text(encoding="utf-8"))


def test_all_contexts_nao_replica_action_no_openapi_mermaid_do_outro(tmp_path: Path):
    """Golden de isolamento: cada contexto publica só o próprio contrato."""
    openapi = run(
        "openapi",
        dry_run=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path / "oa",
        run_id="iso-oa",
        all_contexts=True,
    )
    mermaid = run(
        "mermaid",
        dry_run=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path / "mm",
        run_id="iso-mm",
        all_contexts=True,
    )
    assert openapi["status"] == "completed", openapi.get("validation")
    assert mermaid["status"] == "completed", mermaid.get("validation")

    oa_by = {c["context"]: c for c in openapi["by_context"]}
    mm_by = {c["context"]: c for c in mermaid["by_context"]}

    cliente_oa = _openapi_doc(oa_by["ms-cliente"])
    pag_oa = _openapi_doc(oa_by["ms-pagamento"])
    assert set(cliente_oa["paths"]) == {"/clientes"}
    assert "/pagamentos" not in cliente_oa["paths"]
    assert set(pag_oa["paths"]) == {"/pagamentos"}
    assert "/clientes" not in pag_oa["paths"]

    cliente_spec = yaml.safe_load(
        Path(oa_by["ms-cliente"]["canonical_spec"]).read_text(encoding="utf-8")
    )
    pag_spec = yaml.safe_load(
        Path(oa_by["ms-pagamento"]["canonical_spec"]).read_text(encoding="utf-8")
    )
    assert {op["name"] for op in cliente_spec["operations"]} == {"cadastrar"}
    assert {op["owner"] for op in cliente_spec["operations"]} == {"ms-cliente"}
    assert {op["name"] for op in pag_spec["operations"]} == {"pagar"}
    assert {op["owner"] for op in pag_spec["operations"]} == {"ms-pagamento"}

    cliente_mm = Path(mm_by["ms-cliente"]["output"]).read_text(encoding="utf-8")
    pag_mm = Path(mm_by["ms-pagamento"]["output"]).read_text(encoding="utf-8")
    assert "/clientes" in cliente_mm and "/pagamentos" not in cliente_mm
    assert "/pagamentos" in pag_mm and "/clientes" not in pag_mm

    # o recorte é o mesmo conjunto que OpenAPI/Mermaid leem (IR, não o renderer)
    assert set(cliente_oa["paths"]) == {
        op["path"] for op in cliente_spec["operations"] if op.get("path")
    }
    assert set(pag_oa["paths"]) == {
        op["path"] for op in pag_spec["operations"] if op.get("path")
    }


def test_run_context_isola_spec_operations(tmp_path: Path):
    result = run(
        "openapi",
        dry_run=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path / "ctx",
        run_id="iso-ctx",
        context="ms-cliente",
    )
    assert result["status"] == "completed", result.get("validation")
    ctx = (result.get("by_context") or [result])[0]
    spec = yaml.safe_load(Path(ctx["canonical_spec"]).read_text(encoding="utf-8"))
    assert {op["name"] for op in spec["operations"]} == {"cadastrar"}
    assert {op["owner"] for op in spec["operations"]} == {"ms-cliente"}
    texto = Path(ctx["output"]).read_text(encoding="utf-8")
    doc = yaml.safe_load(texto)
    assert set(doc["paths"]) == {"/clientes"}
    assert "/pagamentos" not in texto

