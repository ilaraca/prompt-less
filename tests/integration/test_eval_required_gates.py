"""Gates obrigatórios de avaliação: dimensões não compensáveis (ticket 30)."""
from __future__ import annotations

from pathlib import Path

import yaml

from src.learning.evals import score_case
from src.runtime.atomic_io import sha256_of
from src.runtime.integrity import seal_hmac
from src.runtime.run_context import RunContext
from src.runtime.run_store import RunStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _base_result(*, service: str = "ms-cliente", run_id: str, run_dir: Path) -> dict:
    return {
        "status": "completed",
        "run_id": run_id,
        "run_dir": str(run_dir),
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


def _spec_body(*, source_claims: list[str] | None = None, blocking: bool = False) -> dict:
    claims = [{"id": "CLM-1", "text": "POST /clientes CPF autenticação"}]
    src = source_claims if source_claims is not None else ["CLM-1"]
    return {
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
        "operations": [
            {
                "id": "OP-1",
                "name": "salvar",
                "owner": "ms-cliente",
                "method": "POST",
                "path": "/clientes",
                "success_status": {
                    "value": 200,
                    "origin": "declared",
                    "confidence": 1.0,
                    "requires_review": False,
                },
                "error_ids": ["ERR-cpf"],
            }
        ],
        "errors": [
            {"id": "ERR-cpf", "trigger": "cpf", "status": 400},
        ],
        "open_questions": (
            [{"id": "Q-1", "text": "pendência bloqueante", "blocking": True}]
            if blocking
            else []
        ),
    }


def _seed(
    root: Path,
    run_id: str,
    *,
    source_claims: list[str] | None = None,
    blocking: bool = False,
    historia: str | None = None,
    prd: str | None = None,
    status: str = "completed",
) -> Path:
    ctx = RunContext.create(root=root, objective="historia", run_id=run_id)
    store = RunStore(ctx)
    store.bootstrap()
    art = ctx.artifacts_dir
    art.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    spec_path = art / "canonical-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(_spec_body(source_claims=source_claims, blocking=blocking)),
        encoding="utf-8",
    )
    files.append(
        {
            "path": "artifacts/canonical-spec.yaml",
            "bytes": spec_path.stat().st_size,
            "sha256": sha256_of(spec_path),
        }
    )
    if historia is not None:
        path = art / "historia.md"
        path.write_text(historia, encoding="utf-8")
        files.append(
            {
                "path": "artifacts/historia.md",
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    if prd is not None:
        path = art / "prd.md"
        path.write_text(prd, encoding="utf-8")
        files.append(
            {
                "path": "artifacts/prd.md",
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    store.finish(status)
    integrity = {
        "algo": "hmac-sha256",
        "kid": "v1",
        "events_tip": store.events.tip,
        "files": files,
        "sealed_at": "2026-09-18T00:00:00Z",
    }
    integrity["hmac"] = seal_hmac(integrity)
    store.write_manifest({"run_id": run_id, "status": status, "integrity": integrity})
    return ctx.run_dir


def _expected(**overrides: object) -> dict:
    base = {
        "services": ["ms-cliente"],
        "http_operations": [
            {
                "service": "ms-cliente",
                "method": "POST",
                "path": "/clientes",
                "success_status": 200,
                "error_statuses": [400],
            }
        ],
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
    run_dir = _seed(tmp_path, "run-miss-art")
    score = score_case(
        _expected(),
        _base_result(run_id="run-miss-art", run_dir=run_dir),
        output_root=tmp_path,
    )
    assert score.layer_scores["canonical_spec"]["expected_signals"] is True
    assert score.required_gates["artifacts_present"] is False
    assert "artifacts_present" in score.fail_reasons
    assert score.passed is False


def test_spec_ok_does_not_compensate_missing_artifact_signals(tmp_path: Path):
    """Sinais na spec não compensam ausência dos mesmos sinais nos artefatos."""
    run_dir = _seed(
        tmp_path,
        "run-art-sig",
        historia="# sem sinais esperados\n",
        prd="# sem sinais esperados\n",
    )
    score = score_case(
        _expected(),
        _base_result(run_id="run-art-sig", run_dir=run_dir),
        output_root=tmp_path,
    )
    assert score.required_gates["spec_signals"] is True
    assert score.required_gates["artifacts_present"] is True
    assert score.required_gates["artifact_signals"] is False
    assert "artifact_signals" in score.fail_reasons
    assert score.passed is False


def test_broken_traceability_fails(tmp_path: Path):
    run_dir = _seed(
        tmp_path,
        "run-trace",
        source_claims=["CLM-INEXISTENTE"],
        historia="POST /clientes CPF\n",
        prd="POST /clientes CPF\n",
    )
    score = score_case(
        _expected(),
        _base_result(run_id="run-trace", run_dir=run_dir),
        output_root=tmp_path,
    )
    assert score.required_gates["traceable"] is False
    assert score.passed is False


def test_wrong_service_fails(tmp_path: Path):
    run_dir = _seed(
        tmp_path,
        "run-svc",
        historia="POST /clientes CPF\n",
        prd="POST /clientes CPF\n",
    )
    result = _base_result(run_id="run-svc", run_dir=run_dir)
    result["contexts"] = ["ms-outro"]
    result["by_context"] = [
        {"servico": {"id": "ms-outro", "repos": ["mfe-onboarding", "bff-cliente", "ms-cliente"]}}
    ]
    score = score_case(_expected(), result, output_root=tmp_path)
    assert score.required_gates["service_match"] is False
    assert score.passed is False


def test_blocking_pendency_fails(tmp_path: Path):
    run_dir = _seed(
        tmp_path,
        "run-block-q",
        blocking=True,
        historia="POST /clientes CPF\n",
        prd="POST /clientes CPF\n",
    )
    score = score_case(
        _expected(),
        _base_result(run_id="run-block-q", run_dir=run_dir),
        output_root=tmp_path,
    )
    assert score.required_gates["no_blocking_pendencies"] is False
    assert score.passed is False


def test_false_dimension_never_compensated_by_another(tmp_path: Path):
    """Artefato ausente + spec/trace ok → fail; não passa por outras dimensões."""
    run_dir = _seed(tmp_path, "run-nocomp")
    score = score_case(
        _expected(),
        _base_result(run_id="run-nocomp", run_dir=run_dir),
        output_root=tmp_path,
    )
    assert score.required_gates["spec_present"] is True
    assert score.required_gates["traceable"] is True
    assert score.required_gates["artifacts_present"] is False
    assert score.passed is False


def test_blocked_case_passes_with_matching_cause(tmp_path: Path):
    run_dir = _seed(tmp_path, "run-exp-block", status="blocked")
    expected = _expected(
        expect_blocked=True,
        artifacts=[],
        critical=False,
        ownership={},
        expected_reason="spec_validation_failed",
        expected_block_codes=["AMBIGUOUS_HTTP_STATUS"],
    )
    result = {
        "status": "blocked",
        "run_id": "run-exp-block",
        "run_dir": str(run_dir),
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
                "claims": [{"id": "CLM-1", "text": "CPF inválido"}],
            }
        ],
        "claims": [{"text": "POST /clientes CPF"}],
    }
    score = score_case(expected, result, output_root=tmp_path)
    assert score.required_gates["block_cause_ok"] is True
    assert score.passed is True


def test_blocked_case_fails_on_wrong_cause(tmp_path: Path):
    run_dir = _seed(tmp_path, "run-bad-cause", status="blocked")
    expected = _expected(
        expect_blocked=True,
        artifacts=[],
        critical=False,
        ownership={},
        expected_reason="spec_validation_failed",
        expected_block_codes=["AMBIGUOUS_HTTP_STATUS"],
    )
    result = {
        "status": "blocked",
        "run_id": "run-bad-cause",
        "run_dir": str(run_dir),
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
        "claims": [{"text": "POST /clientes CPF"}],
    }
    score = score_case(expected, result, output_root=tmp_path)
    assert score.required_gates["block_cause_ok"] is False
    assert score.passed is False


def test_fixture_ambiguous_status_declares_expected_cause():
    expected = yaml.safe_load(
        (FIXTURES / "ambiguous_status" / "expected.yaml").read_text(encoding="utf-8")
    )
    assert expected.get("expect_blocked") is True
    assert expected.get("expected_reason") or expected.get("block_reason")
