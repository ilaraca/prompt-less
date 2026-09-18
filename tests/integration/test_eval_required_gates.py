"""Gates obrigatórios de avaliação: dimensões não compensáveis (ticket 30)."""
from __future__ import annotations

from pathlib import Path

import yaml

from src.learning.evals import score_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _base_result(*, service: str = "ms-cliente") -> dict:
    return {
        "status": "completed",
        "contexts": [service],
        "by_context": [
            {
                "servico": {
                    "id": service,
                    "repos": ["mfe-onboarding", "bff-cliente", "ms-cliente"],
                }
            }
        ],
        "claims": [{"text": "POST /clientes CPF autenticação"}],
    }


def _write_spec(out: Path, *, source_claims: list[str] | None = None, blocking: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    claims = [{"id": "CLM-1", "text": "POST /clientes CPF autenticação"}]
    src = source_claims if source_claims is not None else ["CLM-1"]
    spec = {
        "service_id": "ms-cliente",
        "claims": claims,
        "requirements": [
            {
                "id": "RF-1",
                "text": "cadastro /clientes",
                "source_claims": src,
                "status": "ok",
            }
        ],
        "acceptance_criteria": [],
        "operations": [],
        "errors": [{"trigger": "ok", "status": 200}, {"trigger": "cpf", "status": 400}],
        "open_questions": (
            [{"id": "Q-1", "text": "pendência bloqueante", "blocking": True}]
            if blocking
            else []
        ),
    }
    (out / "canonical-spec.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")


def _expected(**overrides: object) -> dict:
    base = {
        "services": ["ms-cliente"],
        "http_statuses": [200, 400],
        "http_status_mode": "subset",
        "signals": ["/clientes", "cpf"],
        "artifacts": ["historia", "prd"],
        "critical": True,
        "ownership": {
            "ms-cliente": ["mfe-onboarding", "bff-cliente", "ms-cliente"],
        },
        "max_unreviewed_inferences": 0,
    }
    base.update(overrides)
    return base


def test_missing_required_artifact_fails_despite_valid_spec(tmp_path: Path):
    """Spec com sinais OK sem história/PRD deve reprovar (sem compensação)."""
    _write_spec(tmp_path)
    score = score_case(_expected(), _base_result(), output_root=tmp_path)
    assert score.layer_scores["canonical_spec"]["expected_signals"] is True
    assert score.required_gates["artifacts_present"] is False
    assert "artifacts_present" in score.fail_reasons
    assert score.passed is False


def test_spec_ok_does_not_compensate_missing_artifact_signals(tmp_path: Path):
    """Sinais na spec não compensam ausência dos mesmos sinais nos artefatos."""
    _write_spec(tmp_path)
    (tmp_path / "historia.md").write_text("# sem sinais esperados\n", encoding="utf-8")
    (tmp_path / "prd.md").write_text("# sem sinais esperados\n", encoding="utf-8")
    score = score_case(_expected(), _base_result(), output_root=tmp_path)
    assert score.required_gates["spec_signals"] is True
    assert score.required_gates["artifacts_present"] is True
    assert score.required_gates["artifact_signals"] is False
    assert "artifact_signals" in score.fail_reasons
    assert score.passed is False


def test_broken_traceability_fails(tmp_path: Path):
    _write_spec(tmp_path, source_claims=["CLM-INEXISTENTE"])
    (tmp_path / "historia.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    (tmp_path / "prd.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    score = score_case(_expected(), _base_result(), output_root=tmp_path)
    assert score.required_gates["traceable"] is False
    assert "traceable" in score.fail_reasons
    assert score.passed is False


def test_wrong_service_fails_despite_other_gates(tmp_path: Path):
    _write_spec(tmp_path)
    (tmp_path / "historia.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    (tmp_path / "prd.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    result = _base_result(service="ms-outro")
    score = score_case(_expected(), result, output_root=tmp_path)
    assert score.required_gates["service_match"] is False
    assert "service_match" in score.fail_reasons
    assert score.passed is False


def test_blocking_pendency_fails(tmp_path: Path):
    _write_spec(tmp_path, blocking=True)
    (tmp_path / "historia.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    (tmp_path / "prd.md").write_text("POST /clientes CPF\n", encoding="utf-8")
    score = score_case(_expected(), _base_result(), output_root=tmp_path)
    assert score.required_gates["no_blocking_pendencies"] is False
    assert "no_blocking_pendencies" in score.fail_reasons
    assert score.passed is False


def test_false_dimension_never_compensated_by_another(tmp_path: Path):
    """Uma dimensão obrigatória falsa permanece em fail_reasons mesmo com as demais OK."""
    _write_spec(tmp_path)
    # artefatos ausentes; restante (serviço, HTTP, spec, trace) OK
    score = score_case(_expected(), _base_result(), output_root=tmp_path)
    assert score.required_gates["spec_signals"] is True
    assert score.required_gates["service_match"] is True
    assert score.required_gates["traceable"] is True
    assert score.required_gates["artifacts_present"] is False
    assert score.passed is False
    assert score.fail_reasons == ["artifacts_present", "artifact_signals"] or (
        "artifacts_present" in score.fail_reasons
    )


def test_blocked_case_requires_expected_cause(tmp_path: Path):
    """Bloqueio sem a causa esperada reprova pelo motivo block_cause_ok."""
    _write_spec(tmp_path)
    expected = {
        "expect_blocked": True,
        "expected_reason": "spec_validation_failed",
        "expected_block_codes": ["AMBIGUOUS_HTTP_STATUS"],
        "services": ["ms-cliente"],
        "http_statuses": [400, 422],
        "http_status_mode": "subset",
        "signals": ["cpf"],
        "artifacts": [],
        "critical": True,
    }
    # blocked, mas causa/código errados
    result = {
        "status": "blocked",
        "contexts": ["ms-cliente"],
        "by_context": [
            {
                "status": "blocked",
                "reason": "input_scan_failed",
                "servico": {"id": "ms-cliente", "repos": ["bff-cliente", "ms-cliente"]},
                "validation": {
                    "status": "blocked",
                    "errors": 1,
                    "warnings": 0,
                    "issues": [{"code": "SECRET_DETECTED", "severity": "error"}],
                },
                "claims": [{"id": "CLM-1", "text": "CPF inválido"}],
            }
        ],
        "claims": [{"text": "CPF inválido"}],
    }
    score = score_case(expected, result, output_root=tmp_path)
    assert score.required_gates["status_ok"] is True
    assert score.required_gates["block_cause_ok"] is False
    assert "block_cause_ok" in score.fail_reasons
    assert score.passed is False
    assert "spec_validation_failed" not in score.details["actual_block_reasons"]


def test_blocked_case_passes_with_matching_cause(tmp_path: Path):
    _write_spec(tmp_path)
    # errors no spec para http_statuses subset
    expected = yaml.safe_load(
        (FIXTURES / "ambiguous_status" / "expected.yaml").read_text(encoding="utf-8")
    )
    result = {
        "status": "blocked",
        "contexts": ["ms-cliente"],
        "by_context": [
            {
                "status": "blocked",
                "reason": "spec_validation_failed",
                "servico": {"id": "ms-cliente", "repos": ["bff-cliente", "ms-cliente"]},
                "validation": {
                    "status": "blocked",
                    "errors": 1,
                    "warnings": 0,
                    "issues": [
                        {"code": "AMBIGUOUS_HTTP_STATUS", "severity": "error"}
                    ],
                },
                "claims": [{"id": "CLM-1", "text": "CPF inválido 400 422"}],
            }
        ],
        "claims": [{"text": "CPF inválido"}],
    }
    # fixture espera 400/422 no spec — escreve statuses
    (tmp_path / "canonical-spec.yaml").write_text(
        yaml.safe_dump(
            {
                "claims": [{"id": "CLM-1", "text": "CPF inválido"}],
                "requirements": [
                    {
                        "id": "RF-1",
                        "text": "CPF",
                        "source_claims": ["CLM-1"],
                        "status": "ok",
                    }
                ],
                "acceptance_criteria": [],
                "operations": [],
                "errors": [{"status": 400}, {"status": 422}],
                "open_questions": [],
            }
        ),
        encoding="utf-8",
    )
    score = score_case(expected, result, output_root=tmp_path)
    assert score.required_gates["block_cause_ok"] is True
    assert score.passed is True


def test_happy_path_still_passes_required_gates(tmp_path: Path):
    report_root = tmp_path / "hp"
    from src.learning.evals import run_eval_suite

    report = run_eval_suite(cases=["happy_path"], output_root=report_root)
    case = report["cases"][0]
    assert case["ok"] is True
    gates = case["score"]["required_gates"]
    assert gates["artifacts_present"] is True
    assert gates["artifact_signals"] is True
    assert gates["traceable"] is True
    assert gates["no_blocking_pendencies"] is True
