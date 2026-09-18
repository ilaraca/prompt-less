"""Gates de verificação por evidência real (Git + log do adapter)."""
from __future__ import annotations

import os
from pathlib import Path

from src.domain.spec import CanonicalSpec
from src.executors.base import ExecutionResult
from src.executors.evidence import inspect_commits, make_evidence_binding, spec_content_hash
from src.executors.verify import verify_execution
from src.spec.builder import build_canonical_spec

from tests.integration.evidence_support import (
    DEFAULT_BASE,
    DEFAULT_RESULT,
    MVNW_TEST,
    evidenced_test,
    git_in,
    make_git_repo,
    mvnw_log_record,
    write_adapter_log,
)


def _spec() -> CanonicalSpec:
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


def _binding(
    spec: CanonicalSpec,
    *,
    base: str,
    result: str,
    run_id: str = "run-ev-001",
) -> dict:
    return make_evidence_binding(
        run_id=run_id,
        repository="bff-cliente",
        base_commit=base,
        result_commit=result,
        spec_hash=spec_content_hash(spec),
    )


def _result(
    spec: CanonicalSpec,
    *,
    base: str,
    result: str,
    changed: list[str],
    tests: list[dict],
    commands: list[str] | None = None,
    trace: dict[str, list[str]] | None = None,
    approved: bool = True,
    run_id: str = "run-ev-001",
) -> ExecutionResult:
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    return ExecutionResult(
        run_id=run_id,
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result,
        changed_files=changed,
        commands_executed=commands if commands is not None else [MVNW_TEST],
        tests=tests,
        requirement_traceability=trace
        or {
            rf: ["src/main/java/ClienteService.java"],
            ac: ["tests/ClienteServiceTest.java"],
        },
        approved=approved,
    )


def _harness_test(
    spec: CanonicalSpec,
    *,
    log_file: Path,
    base: str,
    result: str,
    name: str = "ClienteServiceTest",
    covers: list[str] | None = None,
    kind: str = "unit",
    exit_code: int = 0,
    run_id: str = "run-ev-001",
) -> tuple[dict, dict]:
    bind = _binding(spec, base=base, result=result, run_id=run_id)
    ac = spec.acceptance_criteria[0].id
    test = evidenced_test(
        name=name,
        log_file=log_file,
        exit_code=exit_code,
        kind=kind,
        covers=covers if covers is not None else [ac],
        binding=bind,
        run_id=run_id,
        base_commit=base,
        result_commit=result,
        spec_hash=spec_content_hash(spec),
    )
    rec = mvnw_log_record(
        exit_code=exit_code,
        log=log_file.name,
        name=name,
        kind=kind,
        binding=bind,
        log_sha256=test["log_sha256"],
    )
    return test, rec


def test_commits_are_mandatory():
    spec = _spec()
    result = ExecutionResult(
        run_id="r",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        changed_files=["src/Foo.java"],
        commands_executed=[MVNW_TEST],
        tests=[{"name": "t", "passed": True}],
        approved=True,
        requirement_traceability={
            spec.requirements[0].id: ["src/Foo.java"],
            spec.acceptance_criteria[0].id: ["src/Foo.java"],
        },
    )
    verify = verify_execution(result, spec, layer="bff")
    codes = {i.code for i in verify.issues}
    assert verify.status == "failed"
    assert "MISSING_BASE_COMMIT" in codes
    assert "MISSING_RESULT_COMMIT" in codes
    assert "MISSING_REPO_EVIDENCE" in codes
    assert "MISSING_ADAPTER_LOG" in codes


def test_forged_payload_cannot_hide_out_of_scope_file(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path,
        base_files=DEFAULT_BASE,
        extra_result={
            **DEFAULT_RESULT,
            "infra/prod/deploy.yaml": "hidden: true\n",
        },
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=["src/main/java/ClienteService.java", "tests/ClienteServiceTest.java"],
        tests=[test],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    codes = {i.code for i in verify.issues}
    assert verify.status == "failed"
    assert "FILE_OUT_OF_SCOPE" in codes
    assert "EVIDENCE_DIVERGENCE" in codes
    assert any(
        i.subject_id == "infra/prod/deploy.yaml" for i in verify.issues if i.code == "FILE_OUT_OF_SCOPE"
    )


def test_declared_test_without_execution_is_rejected(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    adapter_log = write_adapter_log(
        tmp_path / "runner" / "adapter-log.jsonl",
        [mvnw_log_record(base_commit=base, result_commit=result_sha)],
    )
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        tests=[{"name": "ClienteServiceTest", "passed": True}],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "TEST_NOT_EVIDENCED" for i in verify.issues)


def test_verify_report_hashes_are_reproducible(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    changed = [
        "src/main/java/ClienteService.java",
        "tests/ClienteServiceTest.java",
    ]
    first = verify_execution(
        _result(spec, base=base, result=result_sha, changed=changed, tests=[test]),
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=adapter_log,
    )
    second = verify_execution(
        _result(spec, base=base, result=result_sha, changed=changed, tests=[test]),
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=adapter_log,
    )
    assert first.status == "passed", [i.to_dict() for i in first.issues]
    assert first.evidence_hashes == second.evidence_hashes
    git = inspect_commits(repo, base, result_sha)
    assert first.evidence_hashes["base_commit"] == git.base_sha
    assert first.evidence_hashes["result_commit"] == git.result_sha
    assert first.evidence_hashes["diff_sha256"]
    assert first.evidence_hashes["adapter_log_sha256"]
    assert first.evidence_hashes["hmac"]
    assert first.evidence_hashes["test_artifacts"]
    assert first.evidence_hashes["test_kinds"]["unit"]


def test_reversed_commits_fail_ancestry(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    # binding usa commits invertidos no payload; evidência harness ainda aponta aos SHAs
    test, rec = _harness_test(
        spec, log_file=log_file, base=result_sha, result=base
    )
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=result_sha,
        result=base,
        changed=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        tests=[test],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "COMMIT_NOT_ANCESTOR" for i in verify.issues)


def test_foreign_commit_is_not_same_repository(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path / "a", base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    other, other_base, other_result = make_git_repo(
        tmp_path / "b",
        base_files={"README.md": "# other\n"},
        extra_result={"src/X.java": "class X {}\n"},
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(
        spec, log_file=log_file, base=other_base, result=other_result
    )
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=other_base,
        result=other_result,
        changed=["src/X.java"],
        tests=[test],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "COMMIT_NOT_IN_REPO" for i in verify.issues)
    assert result_sha
    assert other != repo
    assert base


def test_policy_uses_realpath_of_symlink(tmp_path: Path):
    spec = _spec()
    repo, base, _ = make_git_repo(
        tmp_path,
        base_files={
            **DEFAULT_BASE,
            "infra/prod/deploy.yaml": "prod: true\n",
            "src/main/java/ClienteService.java": "class ClienteService {}\n",
            "tests/ClienteServiceTest.java": "class ClienteServiceTest {}\n",
        },
    )
    sneaky = repo / "src" / "sneaky.yaml"
    sneaky.symlink_to(os.path.relpath(repo / "infra" / "prod" / "deploy.yaml", sneaky.parent))

    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-m", "symlink")
    result_sha = git_in(repo, "rev-parse", "HEAD").strip()

    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=["src/sneaky.yaml"],
        tests=[test],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    codes = {i.code for i in verify.issues}
    assert verify.status == "failed"
    assert "FILE_OUT_OF_SCOPE" in codes
    assert any(i.subject_id == "src/sneaky.yaml" for i in verify.issues)


def test_traceability_must_exist_in_result_commit(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        tests=[test],
        trace={
            spec.requirements[0].id: ["src/main/java/Missing.java:99"],
            spec.acceptance_criteria[0].id: ["tests/ClienteServiceTest.java:1"],
        },
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "TRACE_NOT_IN_RESULT_COMMIT" for i in verify.issues)


def test_command_payload_divergence_is_error(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [rec])
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        tests=[test],
        commands=["./mvnw test", "terraform apply"],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "EVIDENCE_DIVERGENCE" for i in verify.issues)
    assert not any(i.code == "COMMAND_DENIED" for i in verify.issues)
