"""Aprovação auditável: vínculo, rejeição, reuse e promoção fail-closed."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.approval import main as approval_main
from src.close_loop import close_loop
from src.domain.spec import CanonicalSpec
from src.executors.base import ExecutionResult
from src.runtime.approval import (
    ApprovalExpired,
    ApprovalMissing,
    ApprovalRejected,
    ApprovalReuse,
    ApprovalTampered,
    approve,
    approval_path,
    promote,
    promotion_path,
    request_approval,
    show_history,
)
from src.runtime.atomic_io import read_json
from src.spec.builder import build_canonical_spec

from tests.integration.evidence_support import (
    DEFAULT_BASE,
    DEFAULT_RESULT,
    MVNW_TEST,
    evidenced_test,
    make_git_repo,
    mvnw_log_record,
    write_adapter_log,
)


def _mini_spec() -> CanonicalSpec:
    return build_canonical_spec(
        ui={"actions": [{"id": "salvar", "method": "POST", "path": "/clientes"}]},
        regras={"bloqueios": [{"trigger": "CPF inválido", "status": 400}]},
        claims=[
            {
                "id": "CLM-1",
                "text": "CPF inválido HTTP 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "regras.yaml"}],
            }
        ],
        servico={"id": "ms-cliente", "nome": "Cliente", "repos": ["bff-cliente"]},
    )


def _passing_execution(
    tmp_path: Path, spec: CanonicalSpec, *, run_id: str
) -> tuple[ExecutionResult, Path, Path]:
    repo, base, result = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [mvnw_log_record()])
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    execution = ExecutionResult(
        run_id=run_id,
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result,
        changed_files=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        commands_executed=[MVNW_TEST],
        tests=[evidenced_test(name="ClienteServiceTest", log_file=log_file)],
        requirement_traceability={
            rf: ["src/main/java/ClienteService.java"],
            ac: ["tests/ClienteServiceTest.java"],
        },
        approved=True,
        adapter_log=str(adapter_log),
    )
    return execution, repo, adapter_log


def _prepare_run(tmp_path: Path, *, run_id: str = "run-apr-001") -> Path:
    spec = _mini_spec()
    execution, repo, adapter_log = _passing_execution(tmp_path, spec, run_id=run_id)
    run_dir = tmp_path / "runs" / run_id
    artifacts = run_dir / "artifacts"
    validations = run_dir / "validations"
    artifacts.mkdir(parents=True)
    validations.mkdir(parents=True)

    spec_path = artifacts / "canonical-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result_path = artifacts / "execution.json"
    result_path.write_text(json.dumps(execution.to_dict()), encoding="utf-8")

    report = close_loop(
        spec_path=spec_path,
        result_path=result_path,
        repo_path=repo,
        adapter_log=adapter_log,
        out_dir=validations,
    )
    assert report["verify"]["status"] == "passed", report["verify"]["issues"]
    return run_dir


def _approve_run(run_dir: Path, *, run_id: str, actor: str = "alice") -> dict:
    request_approval(run_dir, run_id=run_id, actor=actor, origin="cli")
    return approve(
        run_dir,
        run_id=run_id,
        actor=actor,
        justification="spec, diff e commit conferem",
        origin="cli",
    )


def test_promote_without_approval_fails(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    with pytest.raises(ApprovalMissing):
        promote(run_dir, run_id="run-apr-001")


def test_approval_record_has_actor_timestamp_justification_origin(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    entry = _approve_run(run_dir, run_id="run-apr-001", actor="alice")
    assert entry["decision"] == "approved"
    assert entry["actor"] == "alice"
    assert entry["timestamp"]
    assert "spec" in (entry.get("justification") or "")
    assert entry["origin"] == "cli"
    binding = entry["binding"]
    assert binding["canonical_spec_sha256"]
    assert binding["verify_report_sha256"]
    assert binding["result_commit"]
    assert binding.get("diff_sha256")
    assert entry["hmac"]
    assert entry["kid"]


def test_changing_spec_expires_approval(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    _approve_run(run_dir, run_id="run-apr-001")
    spec = run_dir / "artifacts" / "canonical-spec.yaml"
    spec.write_text(spec.read_text(encoding="utf-8") + "\n# adulterado\n", encoding="utf-8")
    with pytest.raises(ApprovalExpired, match="canonical_spec_sha256"):
        promote(run_dir, run_id="run-apr-001")


def test_changing_verify_report_expires_approval(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    _approve_run(run_dir, run_id="run-apr-001")
    report_path = run_dir / "validations" / "verify-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    hashes = report["verify"]["evidence_hashes"]
    hashes["diff_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ApprovalExpired, match="verify_report_sha256"):
        promote(run_dir, run_id="run-apr-001")


def test_changing_result_commit_expires_approval(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    _approve_run(run_dir, run_id="run-apr-001")
    result_path = run_dir / "artifacts" / "execution.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["result_commit"] = "deadbeef" * 5
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ApprovalExpired, match="result_commit"):
        promote(run_dir, run_id="run-apr-001")


def test_rejection_is_persisted_and_blocks_promote(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    request_approval(run_dir, run_id="run-apr-001", actor="bob", origin="cli")
    rejected = approve(
        run_dir,
        run_id="run-apr-001",
        actor="bob",
        justification="diff fora do combinado",
        origin="review",
        reject=True,
    )
    assert rejected["decision"] == "rejected"
    history = show_history(run_dir, run_id="run-apr-001")
    decisions = [e["decision"] for e in history["history"]]
    assert "rejected" in decisions
    with pytest.raises(ApprovalRejected):
        promote(run_dir, run_id="run-apr-001")


def test_approval_cannot_be_reused_across_runs(tmp_path: Path):
    run_a = _prepare_run(tmp_path / "a", run_id="run-apr-aaa")
    _approve_run(run_a, run_id="run-apr-aaa")
    run_b = _prepare_run(tmp_path / "b", run_id="run-apr-bbb")
    src = approval_path(run_a)
    dest = approval_path(run_b)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ApprovalReuse):
        promote(run_b, run_id="run-apr-bbb")


def test_tampering_approval_file_invalidates_hmac(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    _approve_run(run_dir, run_id="run-apr-001")
    path = approval_path(run_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["history"][-1]["actor"] = "intruso"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ApprovalTampered):
        promote(run_dir, run_id="run-apr-001")


def test_cli_request_approve_promote_happy_path(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    approval_main(
        ["request-approval", "--run-dir", str(run_dir), "--run-id", "run-apr-001"]
    )
    approval_main(
        [
            "approve",
            "--run-dir",
            str(run_dir),
            "--run-id",
            "run-apr-001",
            "--actor",
            "carol",
            "--justification",
            "ok para promover",
            "--origin",
            "cli",
        ]
    )
    approval_main(
        ["promote", "--run-dir", str(run_dir), "--run-id", "run-apr-001"]
    )
    promo = read_json(promotion_path(run_dir))
    assert promo["run_id"] == "run-apr-001"
    assert promo["hmac"]
    shown = show_history(run_dir, run_id="run-apr-001")
    assert [e["decision"] for e in shown["history"]] == ["requested", "approved"]


def test_cli_promote_without_approval_exits(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    with pytest.raises(SystemExit) as exc:
        approval_main(
            ["promote", "--run-dir", str(run_dir), "--run-id", "run-apr-001"]
        )
    assert exc.value.code == 2


def test_approve_without_pending_request_fails(tmp_path: Path):
    run_dir = _prepare_run(tmp_path, run_id="run-apr-001")
    with pytest.raises(ApprovalMissing):
        approve(
            run_dir,
            run_id="run-apr-001",
            actor="alice",
            justification="sem pedido",
        )
