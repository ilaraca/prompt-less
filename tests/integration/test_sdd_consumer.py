"""Consumidor SDD: Canonical Spec → arquitetura, API decisions e tasks rastreáveis."""
from __future__ import annotations

from pathlib import Path
import yaml

from src.domain.spec import CanonicalSpec, OpenQuestion, Operation
from src.planning.plan import build_implementation_plan
from src.renderers.sdd import build_sdd_package, render_sdd
from src.run import run
from src.spec.builder import build_canonical_spec
from src.validators import validate_derived_artifact, validate_sdd_package

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _spec_cliente() -> CanonicalSpec:
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
            ],
            "actions": [{"id": "salvar", "method": "POST", "path": "/clientes"}],
        },
        regras={
            "bloqueios": [
                {"trigger": "CPF inválido", "status": 400, "code": "CPF_INVALIDO"},
            ],
            "decisoes": [
                {"quando": "payload válido", "entao": "persistir e retornar 201"}
            ],
        },
        engenharia={
            "resiliencia": {"timeout_ms": 2000},
            "observabilidade": {"logs": {"formato": "json"}},
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
        servico={
            "id": "ms-cliente",
            "nome": "Cadastro de Cliente",
            "repos": ["ms-cliente", "bff-cliente", "mfe-onboarding"],
        },
    )


def _spec_two_ops() -> CanonicalSpec:
    spec = _spec_cliente()
    extra = Operation(
        id="OP-002",
        name="listar",
        owner="ms-cliente",
        method="GET",
        path="/clientes",
        method_origin="declared",
        path_origin="declared",
    )
    spec.operations.append(extra)
    spec.open_questions.append(
        OpenQuestion(
            id="Q-BLK",
            text="Operação OP-001 (salvar) — qual payload de erro prevalece?",
            blocking=True,
            source_claims=[],
        )
    )
    spec.open_questions.append(
        OpenQuestion(
            id="Q-OTHER",
            text="Pergunta sem recorte de operação — só revisão de pacote",
            blocking=True,
            source_claims=[],
        )
    )
    return spec


def test_sdd_le_canonical_spec_como_fonte():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    assert package["source"] == "canonical-spec"
    assert package["service_id"] == spec.service_id
    yaml_text = render_sdd(spec)
    assert "canonical-spec" in yaml_text
    assert "PRD.md" not in yaml_text


def test_sdd_gera_architecture_api_e_tasks():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    assert package["architecture"]["origin"] == "canonical-spec"
    assert package["architecture"]["decisions"]
    assert package["api_decisions"]
    assert package["tasks"]
    op_ids = {op.id for op in spec.contract_operations()}
    assert {d["operation_id"] for d in package["api_decisions"]} == op_ids
    for decision in package["architecture"]["decisions"]:
        assert decision["origin"] not in {"renderer", "invented", "scaffold"}


def test_cada_task_referencia_rf_ac_nfr_servico_evidencia():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    rf = spec.requirement_ids()
    ac = {a.id for a in spec.acceptance_criteria}
    nfr = {n.id for n in spec.nfrs}
    for task in package["tasks"]:
        assert task["service_id"] == spec.service_id
        assert set(task["rf_ids"]) <= rf and task["rf_ids"]
        assert set(task["ac_ids"]) <= ac and task["ac_ids"]
        assert set(task["nfr_ids"]) <= nfr
        assert "nfr_ids" in task
        assert isinstance(task["evidence"], list)
        assert task["evidence_status"] in {
            "index_not_applied",
            "observed",
            "none_observed",
        }
        assert task["executor_dispatch"] is False
        assert task["status"] in {"pending_review", "blocked"}


def test_cem_por_cento_tasks_ligadas_a_rf_ac():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    unlinked = [
        t["id"] for t in package["tasks"] if not t.get("rf_ids") or not t.get("ac_ids")
    ]
    assert unlinked == []
    result = validate_sdd_package(spec, package)
    assert not result.has_errors, result.to_dict()


def test_dependencias_reutilizam_grafo_multi_repo():
    spec = _spec_cliente()
    repos = ["ms-cliente", "bff-cliente", "mfe-onboarding"]
    plan = build_implementation_plan(service_id="ms-cliente", repos=repos)
    package = build_sdd_package(spec)
    by_plan = {}
    for task in package["tasks"]:
        by_plan.setdefault(task["plan_task_id"], []).append(task)
    for plan_task in plan["tasks"]:
        sdd_tasks = by_plan[plan_task["id"]]
        expected_deps = set(plan_task["depends_on"])
        for sdd in sdd_tasks:
            got = {d.split("::", 1)[0] for d in sdd["depends_on"]}
            assert got == expected_deps
    assert package["graph"]["source"] == "src.planning.plan.build_implementation_plan"
    api = next(t for t in plan["tasks"] if t["layer"] == "api")
    bff = next(t for t in plan["tasks"] if t["layer"] == "bff")
    assert api["id"] in bff["depends_on"]
    bff_sdd = next(t for t in package["tasks"] if t["plan_task_id"] == bff["id"])
    assert any(d.startswith(api["id"]) for d in bff_sdd["depends_on"])


def test_pergunta_bloqueia_so_escopo_afetado():
    spec = _spec_two_ops()
    package = build_sdd_package(spec)
    op1 = [t for t in package["tasks"] if t["operation_id"] == "OP-001"]
    op2 = [t for t in package["tasks"] if t["operation_id"] == "OP-002"]
    assert op1 and op2
    assert all(t["status"] == "blocked" for t in op1)
    assert all(any(b["id"] == "Q-BLK" for b in t["blocked_by"]) for t in op1)
    assert all(t["status"] == "pending_review" for t in op2)
    assert all(not any(b["id"] == "Q-BLK" for b in t["blocked_by"]) for t in op2)
    unscoped_ids = {q["id"] for q in package["review"]["unscoped_questions"]}
    assert "Q-OTHER" in unscoped_ids
    assert all(not any(b["id"] == "Q-OTHER" for b in t["blocked_by"]) for t in package["tasks"])


def test_so_contract_operations_viram_api_decision():
    spec = _spec_cliente()
    spec.operations.append(
        Operation(id="OP-099", name="rascunho", unresolved=["owner", "method", "path"])
    )
    package = build_sdd_package(spec)
    assert "OP-099" not in {d["operation_id"] for d in package["api_decisions"]}
    unresolved = {u["id"] for u in package["architecture"]["unresolved_operations"]}
    assert "OP-099" in unresolved


def test_schema_rejeita_decisao_do_renderer():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    package["architecture"]["decisions"][0]["origin"] = "renderer"
    result = validate_sdd_package(spec, package)
    assert result.has_errors
    assert any(i.code == "SDD_RENDERER_DECISION" for i in result.errors)


def test_schema_rejeita_despacho_prematuro():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    package["review"]["executor_dispatch"] = True
    package["tasks"][0]["executor_dispatch"] = True
    result = validate_sdd_package(spec, package)
    codes = {i.code for i in result.errors}
    assert "SDD_PREMATURE_DISPATCH" in codes


def test_schema_rejeita_task_sem_rf_ac():
    spec = _spec_cliente()
    package = build_sdd_package(spec)
    package["tasks"][0]["rf_ids"] = []
    package["tasks"][0]["ac_ids"] = []
    result = validate_sdd_package(spec, package)
    assert any(i.code == "SDD_TASK_UNLINKED" for i in result.errors)


def test_render_passa_pelo_gate_de_schema():
    spec = _spec_cliente()
    artifact = render_sdd(spec)
    result = validate_derived_artifact("sdd", artifact, spec)
    assert not result.has_errors, result.to_dict()


def test_run_sdd_emite_pacote_sem_despacho(tmp_path: Path):
    result = run(
        "sdd",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="sdd-happy",
        no_split=True,
    )
    assert result["status"] == "completed", result.get("validation")
    path = Path(result["outputs"]["sdd"])
    assert path.is_file()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["source"] == "canonical-spec"
    assert doc["review"]["executor_dispatch"] is False
    assert doc["review"]["ready_for_executor"] is False
    assert all(t.get("executor_dispatch") is False for t in doc["tasks"])
    assert all(t["status"] != "dispatched" for t in doc["tasks"])
    assert "executor" in (doc["review"].get("note") or "").lower()


def test_run_sdd_isola_operations_por_contexto(tmp_path: Path):
    result = run(
        "sdd",
        dry_run=True,
        inputs_dir=FIXTURES / "two_services",
        output_root=tmp_path,
        run_id="sdd-two",
        all_contexts=True,
    )
    assert result["status"] == "completed", result.get("validation")
    by_id = {
        (c.get("servico") or {}).get("id"): c for c in result.get("by_context") or []
    }
    cliente = yaml.safe_load(Path(by_id["ms-cliente"]["outputs"]["sdd"]).read_text())
    pagamento = yaml.safe_load(Path(by_id["ms-pagamento"]["outputs"]["sdd"]).read_text())
    assert {d["path"] for d in cliente["api_decisions"]} == {"/clientes"}
    assert {d["path"] for d in pagamento["api_decisions"]} == {"/pagamentos"}


def test_historia_also_emit_inclui_sdd(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="sdd-also",
        no_split=True,
    )
    assert "sdd" in result["outputs"]
    assert Path(result["outputs"]["sdd"]).is_file()
