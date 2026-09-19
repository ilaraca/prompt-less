"""36-repair-policy: política completa na superfície de reparo."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.executors.close_loop import close_loop
from src.executors.base import ExecutionResult
from src.executors.loop import MAX_REPAIR_ATTEMPTS, build_repair_request
from src.executors.policy import load_profiles
from src.executors.verify import VerifyIssue, VerifyResult
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


def _mini_spec():
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


def _failed_verify(*issues: VerifyIssue) -> VerifyResult:
    return VerifyResult(status="failed", issues=list(issues))


def _exec(*, changed: list[str] | None = None) -> ExecutionResult:
    files = (
        ["src/main/java/ClienteService.java"]
        if changed is None
        else list(changed)
    )
    return ExecutionResult(
        run_id="run-repair-001",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        changed_files=files,
        commands_executed=[MVNW_TEST],
        tests=[],
        approved=True,
    )


def test_repair_denies_traversal_absolute_and_rf_ids(tmp_path: Path):
    profile = load_profiles()["bff"]
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src" / "main" / "java").mkdir(parents=True)
    (repo / "src" / "main" / "java" / "ClienteService.java").write_text(
        "class X {}\n", encoding="utf-8"
    )

    verify = _failed_verify(
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="escape relativo",
            subject_id="../outside.py",
        ),
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="absoluto",
            subject_id="/tmp/evil.py",
        ),
        VerifyIssue(
            code="RF_NOT_MAPPED",
            severity="error",
            message="rf",
            subject_id="RF-001",
        ),
        VerifyIssue(
            code="AC_NOT_MAPPED",
            severity="error",
            message="ac",
            subject_id="AC-001",
        ),
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="falha real",
            subject_id="tests/ClienteServiceTest.java",
        ),
        VerifyIssue(
            code="FILE_OUT_OF_SCOPE",
            severity="error",
            message="prod",
            subject_id="infra/prod/deploy.yaml",
        ),
    )
    result = _exec(
        changed=[
            "src/main/java/ClienteService.java",
            "infra/prod/deploy.yaml",
        ]
    )
    repair = build_repair_request(
        verify, result, attempt=1, profile=profile, layer="bff", repo_root=repo
    )
    assert repair["status"] == "repair_requested"
    assert "infra/prod/deploy.yaml" in repair["required_reverts"]
    assert "infra/prod/deploy.yaml" not in repair["editable_surface"]
    assert "../outside.py" not in repair["editable_surface"]
    assert "/tmp/evil.py" not in repair["editable_surface"]
    assert "RF-001" not in repair["editable_surface"]
    assert "AC-001" not in repair["editable_surface"]
    assert "tests/ClienteServiceTest.java" in repair["editable_surface"]
    assert "src/main/java/ClienteService.java" in repair["editable_surface"]
    denied_paths = {d["path"] for d in repair["denied_paths"]}
    assert "../outside.py" in denied_paths
    assert "/tmp/evil.py" in denied_paths


def test_repair_denies_symlink_escape(tmp_path: Path):
    profile = load_profiles()["bff"]
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("x", encoding="utf-8")
    (repo / "src" / "leak").symlink_to(outside)

    verify = _failed_verify(
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="via symlink",
            subject_id="src/leak/leak.py",
        )
    )
    repair = build_repair_request(
        verify,
        _exec(changed=["src/main/java/Ok.java"]),
        attempt=1,
        profile=profile,
        layer="bff",
        repo_root=repo,
    )
    assert "src/leak/leak.py" not in repair["editable_surface"]
    assert any(d["path"] == "src/leak/leak.py" for d in repair["denied_paths"])


def test_repair_diagnostic_path_only_when_authorized(tmp_path: Path):
    profile = load_profiles()["bff"]
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)

    verify = _failed_verify(
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="ok",
            subject_id="tests/UnitTest.java",
        ),
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="fora do allow",
            subject_id="build.gradle",
        ),
    )
    repair = build_repair_request(
        verify,
        _exec(changed=[]),
        attempt=1,
        profile=profile,
        layer="bff",
        repo_root=repo,
    )
    assert repair["editable_surface"] == ["tests/UnitTest.java"]
    assert any(d["path"] == "build.gradle" for d in repair["denied_paths"])


def test_repair_fail_closed_without_profile():
    verify = _failed_verify(
        VerifyIssue(
            code="TEST_FAILED",
            severity="error",
            message="x",
            subject_id="src/Foo.java",
        )
    )
    repair = build_repair_request(
        verify,
        _exec(changed=["src/Foo.java"]),
        attempt=1,
        profile=None,
        layer="unknown",
        profiles={},
    )
    assert repair["editable_surface"] == []
    assert repair["denied_paths"]


def test_repair_exhausted_is_unresolved():
    verify = _failed_verify(
        VerifyIssue(code="TEST_FAILED", severity="error", message="still", subject_id="t")
    )
    out = build_repair_request(
        verify,
        _exec(),
        attempt=MAX_REPAIR_ATTEMPTS + 1,
        profile=load_profiles()["bff"],
        layer="bff",
    )
    assert out["status"] == "exhausted"
    assert out["unresolved"] is True


def test_close_loop_reapplies_policy_and_re_verifies_after_fix(tmp_path: Path):
    """Cada close_loop re-verifica; com execução corrigida, repair some."""
    spec = _mini_spec()
    spec_path = tmp_path / "canonical-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    from src.executors.evidence import spec_content_hash

    shash = spec_content_hash(spec)
    test_rec = evidenced_test(
        name="ClienteServiceTest",
        log_file=log_file,
        run_id="run-fixed-001",
        base_commit=base,
        result_commit=result_sha,
        spec_hash=shash,
        covers=[ac],
    )
    adapter_log = write_adapter_log(
        runner / "adapter-log.jsonl",
        [
            mvnw_log_record(
                run_id="run-fixed-001",
                base_commit=base,
                result_commit=result_sha,
                spec_hash=shash,
                log_sha256=test_rec["log_sha256"],
            )
        ],
    )
    execution = ExecutionResult(
        run_id="run-fixed-001",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        base_commit=base,
        result_commit=result_sha,
        changed_files=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        commands_executed=[MVNW_TEST],
        tests=[test_rec],
        requirement_traceability={
            rf: ["src/main/java/ClienteService.java"],
            ac: ["tests/ClienteServiceTest.java"],
        },
        approved=True,
        adapter_log=str(adapter_log),
    )
    result_path = tmp_path / "execution.json"
    result_path.write_text(json.dumps(execution.to_dict()), encoding="utf-8")

    report = close_loop(
        spec_path=spec_path,
        result_path=result_path,
        repo_path=repo,
        adapter_log=adapter_log,
        attempt=2,
        layer="bff",
        out_dir=tmp_path / "verify",
    )
    assert report["verify"]["status"] == "passed"
    assert report["repair"] is None
