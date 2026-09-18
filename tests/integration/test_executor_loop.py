"""Ciclo executor: verify, policy, approval e reparo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.close_loop import close_loop
from src.domain.spec import CanonicalSpec
from src.executors import DevinAdapter, build_repair_request, verify_execution
from src.executors.base import ExecutionResult
from src.executors.policy import check_command_allowed, check_write_allowed, load_profiles
from src.spec.builder import build_canonical_spec

from tests.integration.evidence_support import (
    DEFAULT_BASE,
    DEFAULT_RESULT,
    MVNW_TEST,
    TEST_TS,
    evidenced_test,
    make_git_repo,
    mvnw_log_record,
    write_adapter_log,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXEC = FIXTURES / "executor"


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


def _passing_bundle(tmp_path: Path, spec: CanonicalSpec) -> tuple[ExecutionResult, Path, Path]:
    repo, base, result = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [mvnw_log_record()])
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    execution = ExecutionResult(
        run_id="run-ok-001",
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


def test_policy_denies_secret_and_prod():
    profiles = load_profiles()
    bff = profiles["bff"]
    assert check_write_allowed("src/Foo.java", bff)
    assert check_write_allowed("./src/Foo.java", bff)
    assert not check_write_allowed("infra/prod/deploy.yaml", bff)
    assert not check_write_allowed("keys/app.pem", bff)


def test_policy_rejects_path_traversal():
    profile = load_profiles()["bff"]
    assert not check_write_allowed("src/../infra/prod/deploy.yaml", profile)
    assert not check_write_allowed("src//../infra/prod/deploy.yaml", profile)
    assert not check_write_allowed("src/../../.github/workflows/ci.yml", profile)
    assert not check_write_allowed("/tmp/Foo.java", profile)
    assert not check_write_allowed(r"C:\repo\src\..\infra\prod\deploy.yaml", profile)
    assert check_write_allowed("src/main/java/Foo.java", profile)


def test_policy_rejects_shell_composition():
    profiles = load_profiles()
    bff = profiles["bff"]
    assert check_command_allowed("./mvnw test", bff)
    assert not check_command_allowed("./mvnw test && terraform apply", bff)
    assert not check_command_allowed("pytest; kubectl delete pods --all", bff)
    assert not check_command_allowed("npm test || rm -rf /", bff)
    assert check_command_allowed(
        {"executable": "./mvnw", "args": ["test"]}, bff
    )


def test_verify_fail_closed_unknown_layer():
    spec = _mini_spec()
    result = ExecutionResult(
        run_id="r",
        agent="devin",
        repository="processador-pagamentos",
        changed_files=["src/Main.java"],
        commands_executed=["./mvnw test"],
        tests=[{"name": "t", "passed": True}],
        approved=True,
    )
    verify = verify_execution(result, spec, layer=None)
    assert verify.status == "failed"
    assert any(i.code == "UNKNOWN_EXECUTION_LAYER" for i in verify.issues)


def test_verify_passes_good_execution(tmp_path: Path):
    spec = _mini_spec()
    result, repo, adapter_log = _passing_bundle(tmp_path, spec)
    verify = verify_execution(
        result, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "passed", [i.to_dict() for i in verify.issues]
    assert not verify.has_errors
    assert verify.evidence_hashes.get("diff_sha256")
    assert verify.evidence_hashes.get("adapter_log_sha256")
    assert verify.evidence_hashes.get("hmac")


def test_verify_fails_out_of_scope_and_unmapped(tmp_path: Path):
    spec = _mini_spec()
    repo, base, result_sha = make_git_repo(
        tmp_path,
        base_files={"README.md": "# x\n"},
        extra_result={
            "src/main/java/ClienteService.java": "class ClienteService {}\n",
            "infra/prod/deploy.yaml": "deploy: prod\n",
            ".github/workflows/deploy.yml": "name: deploy\n",
        },
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    adapter_log = write_adapter_log(
        runner / "adapter-log.jsonl",
        [
            {
                "timestamp": TEST_TS,
                "command": "terraform apply",
                "exit_code": 1,
            }
        ],
    )
    result = ExecutionResult(
        run_id="run-bad-001",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result_sha,
        changed_files=[
            "src/main/java/ClienteService.java",
            "infra/prod/deploy.yaml",
            ".github/workflows/deploy.yml",
        ],
        commands_executed=["terraform apply"],
        tests=[
            evidenced_test(
                name="ClienteServiceTest",
                log_file=log_file,
                command="terraform apply",
                exit_code=1,
            )
        ],
        unresolved_items=["auth edge case"],
        requirement_traceability={},
        approved=True,
    )
    verify = verify_execution(
        result, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    codes = {i.code for i in verify.issues}
    assert "FILE_OUT_OF_SCOPE" in codes
    assert "COMMAND_DENIED" in codes
    assert "TEST_FAILED" in codes
    assert "RF_NOT_MAPPED" in codes


def test_verify_no_tests_is_error_for_code_change(tmp_path: Path):
    spec = _mini_spec()
    repo, base, result_sha = make_git_repo(
        tmp_path,
        base_files={"README.md": "# x\n"},
        extra_result={"src/main/java/Foo.java": "class Foo {}\n"},
    )
    adapter_log = write_adapter_log(
        tmp_path / "runner" / "adapter-log.jsonl", [mvnw_log_record()]
    )
    result = ExecutionResult(
        run_id="r",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result_sha,
        changed_files=["src/main/java/Foo.java"],
        commands_executed=[MVNW_TEST],
        tests=[],
        requirement_traceability={
            spec.requirements[0].id: ["src/main/java/Foo.java"],
            spec.acceptance_criteria[0].id: ["src/main/java/Foo.java"],
        },
        approved=True,
    )
    verify = verify_execution(
        result, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "NO_TESTS_REPORTED" and i.severity == "error" for i in verify.issues)


def test_needs_approval_gate(tmp_path: Path):
    spec = _mini_spec()
    result, repo, adapter_log = _passing_bundle(tmp_path, spec)
    result.approved = False
    result.run_id = "run-pending-001"
    verify = verify_execution(
        result, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "needs_approval"


def test_repair_request_requires_approval(tmp_path: Path):
    spec = _mini_spec()
    repo, base, result_sha = make_git_repo(
        tmp_path,
        base_files={"README.md": "# x\n"},
        extra_result={
            "src/main/java/ClienteService.java": "class ClienteService {}\n",
            "infra/prod/deploy.yaml": "deploy: prod\n",
            ".github/workflows/deploy.yml": "name: deploy\n",
        },
    )
    runner = tmp_path / "runner"
    adapter_log = write_adapter_log(
        runner / "adapter-log.jsonl",
        [{"timestamp": TEST_TS, "command": "terraform apply", "exit_code": 1}],
    )
    result = ExecutionResult(
        run_id="run-bad-001",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result_sha,
        changed_files=[
            "src/main/java/ClienteService.java",
            "infra/prod/deploy.yaml",
            ".github/workflows/deploy.yml",
        ],
        commands_executed=["terraform apply"],
        tests=[
            evidenced_test(
                name="ClienteServiceTest",
                log_file=runner / "t.txt",
                command="terraform apply",
                exit_code=1,
            )
        ],
        unresolved_items=["auth edge case"],
        requirement_traceability={},
        approved=True,
    )
    verify = verify_execution(
        result, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    repair = build_repair_request(
        verify, result, attempt=1, profile=load_profiles()["bff"], layer="bff", repo_root=repo
    )
    assert repair is not None
    assert repair["status"] == "repair_requested"
    assert repair["requires_approval"] is True
    assert "infra/prod/deploy.yaml" in repair["required_reverts"]
    assert ".github/workflows/deploy.yml" in repair["required_reverts"]
    assert "infra/prod/deploy.yaml" not in repair["editable_surface"]
    assert "RF-001" not in repair["editable_surface"]
    assert "src/main/java/ClienteService.java" in repair["editable_surface"]
    exhausted = build_repair_request(
        verify, result, attempt=3, profile=load_profiles()["bff"], layer="bff"
    )
    assert exhausted["status"] == "exhausted"
    assert exhausted["unresolved"] is True


def test_devin_adapter_prepare_and_collect(tmp_path: Path):
    adapter = DevinAdapter()
    prep = adapter.prepare(
        run_id="r1", artifacts_dir=str(tmp_path), repository="bff-cliente"
    )
    assert prep["agent"] == "devin"
    assert "canonical_spec" in prep["handoff"]
    payload = json.loads((EXEC / "execution_ok.json").read_text(encoding="utf-8"))
    collected = adapter.collect_result(payload)
    assert collected.run_id == "run-ok-001"


def test_close_loop_passes_without_legacy_approve_flag(tmp_path: Path):
    spec = _mini_spec()
    spec_path = tmp_path / "canonical-spec.yaml"
    import yaml

    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    execution, repo, adapter_log = _passing_bundle(tmp_path, spec)
    result_path = tmp_path / "execution.json"
    result_path.write_text(json.dumps(execution.to_dict()), encoding="utf-8")

    ok = close_loop(
        spec_path=spec_path,
        result_path=result_path,
        repo_path=repo,
        adapter_log=adapter_log,
        out_dir=tmp_path / "verify",
    )
    assert ok["verify"]["status"] == "passed", ok["verify"]["issues"]


def test_close_loop_cli_rejects_legacy_approve(tmp_path: Path, monkeypatch, capsys):
    spec = _mini_spec()
    spec_path = tmp_path / "canonical-spec.yaml"
    import yaml

    from src.close_loop import main as close_loop_main

    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    execution, repo, adapter_log = _passing_bundle(tmp_path, spec)
    result_path = tmp_path / "execution.json"
    result_path.write_text(json.dumps(execution.to_dict()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "close_loop",
            "--spec",
            str(spec_path),
            "--result",
            str(result_path),
            "--repo",
            str(repo),
            "--adapter-log",
            str(adapter_log),
            "--approve",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        close_loop_main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "src.approval" in err
    assert "approved=True" in err
