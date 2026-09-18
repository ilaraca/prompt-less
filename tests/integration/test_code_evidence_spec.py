"""Evidência de código no Canonical Spec: estado atual, gaps e origem observed."""
from __future__ import annotations

from pathlib import Path

from src.domain.spec import CanonicalSpec
from src.renderers import render_historia, render_prd
from src.repo_index import index_repo
from src.run import run
from src.spec.builder import build_canonical_spec

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HISTORIA_TPL = (ROOT / "templates" / "historia.skeleton.md").read_text(encoding="utf-8")
PRD_TPL = (ROOT / "templates" / "prd.skeleton.md").read_text(encoding="utf-8")

_CONTROLLER = """\
@RequestMapping("/clientes")
public class ClienteController {
    @PostMapping("/cadastro")
    public ResponseEntity<?> salvar() {
        return ResponseEntity.status(201).body(ok);
    }

    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public void cpfInvalido() {}
}
"""


def _write_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "cadastro-cliente-api"
    src = repo / "src" / "main" / "java"
    src.mkdir(parents=True)
    (src / "ClienteController.java").write_text(_CONTROLLER, encoding="utf-8")
    return repo


def _indice_from_repo(tmp_path: Path) -> dict:
    repo = _write_repo(tmp_path)
    return index_repo(repo)


def _spec_sem_indice() -> CanonicalSpec:
    return build_canonical_spec(
        ui={"actions": [{"id": "salvar", "method": "POST", "path": "/clientes"}]},
        regras={
            "bloqueios": [{"trigger": "CPF inválido", "status": 400}],
            "decisoes": [{"quando": "ok", "entao": "retornar 200"}],
        },
        claims=[
            {
                "id": "CLM-0001",
                "text": "CPF inválido devolve 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
        servico={"id": "ms-cliente", "nome": "Cadastro"},
    )


def test_canonical_spec_modela_current_state_gaps_e_code_evidence():
    spec = _spec_sem_indice()
    dumped = spec.to_dict()
    assert "current_state" in dumped
    assert "gaps" in dumped
    assert "code_evidence" in dumped
    assert dumped["current_state"]["applied"] is False
    assert dumped["gaps"] == []
    assert dumped["code_evidence"] == []


def test_repo_index_aponta_arquivo_simbolo_linha_rota_e_confianca(tmp_path: Path):
    idx = _indice_from_repo(tmp_path)
    rotas = [e for e in idx["evidencias"] if e["kind"] == "route"]
    assert rotas, "deve extrair rota HTTP"
    hit = rotas[0]
    assert hit["file"].endswith("ClienteController.java")
    assert hit["symbol"] == "ClienteController"
    assert isinstance(hit["line"], int) and hit["line"] >= 1
    assert "POST" in hit["route"] and "/clientes" in hit["route"]
    assert 0.0 <= hit["confidence"] <= 1.0
    assert hit["origin"] in {"observed", "heuristic"}


def test_metodo_path_status_observados_resolvem_campos(tmp_path: Path):
    idx = _indice_from_repo(tmp_path)
    spec = build_canonical_spec(
        ui={"actions": [{"id": "salvar"}]},
        regras={"bloqueios": [{"trigger": "CPF inválido", "status": 400}]},
        claims=[
            {
                "id": "CLM-0001",
                "text": "CPF inválido devolve 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
        servico={"id": "ms-cliente", "indice": idx},
    )
    op = spec.operations[0]
    assert op.method == "POST"
    assert op.path == "/clientes/cadastro"
    assert op.method_origin == "observed"
    assert op.path_origin == "observed"
    status = op.success_status
    assert status.origin == "observed"
    assert status.value == 201
    assert op.resolved_success_status() == 201
    assert spec.current_state.applied is True
    assert spec.code_evidence
    assert any(e.file and e.line and e.route for e in spec.code_evidence)


def test_conflito_regra_vs_codigo_abre_pergunta(tmp_path: Path):
    idx = _indice_from_repo(tmp_path)
    spec = build_canonical_spec(
        ui={
            "actions": [
                {"id": "salvar", "method": "PUT", "path": "/clientes/cadastro"}
            ]
        },
        regras={
            "bloqueios": [{"trigger": "CPF inválido", "status": 400}],
            "decisoes": [{"quando": "ok", "entao": "persistir e retornar 200"}],
        },
        claims=[
            {
                "id": "CLM-0001",
                "text": "CPF inválido devolve 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
        servico={"id": "ms-cliente", "indice": idx},
    )
    conflitos = [g for g in spec.gaps if g.kind == "conflict"]
    assert conflitos, "divergência PUT vs POST deve virar gap"
    assert all(g.origin in {"observed", "heuristic"} for g in conflitos)
    assert all(g.evidence for g in conflitos)
    perguntas = [q.text for q in spec.open_questions]
    assert any("PUT" in t and "POST" in t for t in perguntas)
    assert any("200" in t and "201" in t for t in perguntas)


def test_historia_e_prd_renderizam_estado_e_gaps_do_ir(tmp_path: Path):
    idx = _indice_from_repo(tmp_path)
    spec = build_canonical_spec(
        ui={"actions": [{"id": "salvar", "method": "POST", "path": "/clientes/cadastro"}]},
        regras={"bloqueios": [{"trigger": "não autenticado", "status": 401}]},
        claims=[
            {
                "id": "CLM-0001",
                "text": "sem token devolve 401",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
        servico={"id": "ms-cliente", "nome": "Cadastro", "indice": idx},
    )
    historia = render_historia(spec, HISTORIA_TPL)
    prd = render_prd(spec, PRD_TPL)
    assert "ClienteController" in historia
    assert "ClienteController" in prd
    assert "GAP-" in historia and "GAP-" in prd
    assert "[heurística]" in historia or "[observado]" in historia
    assert "sem gaps" not in historia.lower()
    assert "sem gaps" not in prd.lower()
    for gap in spec.gaps:
        rendered = historia + prd
        assert gap.id in rendered
        assert "[observado]" in rendered or "[heurística]" in rendered
        if gap.origin == "observed":
            assert gap.evidence


def test_ausencia_de_evidencia_nao_vira_sem_gaps():
    spec = _spec_sem_indice()
    historia = render_historia(spec, HISTORIA_TPL)
    prd = render_prd(spec, PRD_TPL)
    assert "índice não aplicado" in historia
    assert "índice não aplicado" in prd
    assert "sem gaps" not in historia.lower()
    assert "sem gaps" not in prd.lower()
    assert spec.current_state.applied is False


def test_regressao_historia_prd_preservam_rf_ac_sem_indice(tmp_path: Path):
    """Comportamento anterior (RF/AC/ownership) permanece sem os novos campos."""
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="code-ev-reg-1",
        no_split=True,
    )
    assert result["status"] == "completed"
    historia = Path(result["outputs"]["historia"]).read_text(encoding="utf-8")
    prd = Path(result["outputs"]["prd"]).read_text(encoding="utf-8")
    spec = _spec_from_run(tmp_path)
    for ac in spec["acceptance_criteria"]:
        assert ac["id"] in historia
        assert ac["id"] in prd
    for rf in spec["requirements"]:
        assert rf["id"] in prd
    assert "Proveniência" in historia
    assert "Proveniência" in prd
    assert "índice não aplicado" in historia
    assert "sem gaps" not in historia.lower()
    assert "sem gaps" not in prd.lower()
    assert spec["current_state"]["applied"] is False


def _spec_from_run(tmp_path: Path) -> dict:
    import yaml

    path = next(tmp_path.rglob("canonical-spec.yaml"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))
