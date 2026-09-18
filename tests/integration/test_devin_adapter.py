"""DevinAdapter real: CLI mock, JSONL, worktree limpo e close_loop."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.close_loop import close_loop
from src.executors import DevinAdapter, verify_execution
from src.executors.base import ExecutionResult
from src.executors.devin import DevinCliError, DirtyWorktreeError
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
    write_files,
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


def _fake_devin_runner(repo: Path, *, files: dict[str, str] | None = None):
    """Simula o CLI: altera arquivos no checkout e retorna exit 0."""

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        assert argv[0] in {"devin", "fake-devin"}
        assert "--print" in argv or "-p" in argv
        root = Path(cwd or repo)
        write_files(root, files or DEFAULT_RESULT)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    return runner


def test_devin_adapter_execute_persists_json_and_log(tmp_path: Path):
    repo, base, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    out = tmp_path / "executor"
    adapter = DevinAdapter(cli_bin="fake-devin", runner=_fake_devin_runner(repo))
    result = adapter.execute(
        run_id="run-devin-001",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out,
        layer="bff",
        prompt="implemente RF-001",
        timeout=30,
        require_enforcement=False,
    )
    assert result.base_commit == base
    assert result.result_commit and result.result_commit != base
    assert "src/main/java/ClienteService.java" in result.changed_files
    assert (out / "execution.json").is_file()
    assert (out / "adapter-log.jsonl").is_file()
    assert (out / "devin-session.json").is_file()
    session = json.loads((out / "devin-session.json").read_text(encoding="utf-8"))
    assert any(e.get("kind") == "invoke" for e in session["events"])
    assert any(e.get("kind") == "commit" for e in session["events"])
    loaded = adapter.collect_result()
    assert loaded.run_id == "run-devin-001"
    assert loaded.adapter_log
    assert loaded.changed_files == result.changed_files


def test_devin_adapter_rejects_dirty_worktree_before_run(tmp_path: Path):
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    (repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    adapter = DevinAdapter(cli_bin="fake-devin", runner=_fake_devin_runner(repo))
    with pytest.raises(DirtyWorktreeError, match="antes da execução"):
        adapter.execute(
            run_id="run-dirty",
            repository="bff-cliente",
            repo_path=repo,
            out_dir=tmp_path / "out",
            prompt="x",
            invoke_cli=True,
            require_enforcement=False,
        )


def test_devin_adapter_cli_failure_is_recorded(tmp_path: Path):
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)

    def boom(argv, **kwargs):
        return SimpleNamespace(returncode=7, stdout="", stderr="boom")

    adapter = DevinAdapter(cli_bin="fake-devin", runner=boom)
    with pytest.raises(DevinCliError, match="código 7"):
        adapter.execute(
            run_id="run-fail",
            repository="bff-cliente",
            repo_path=repo,
            out_dir=tmp_path / "out",
            prompt="x",
            require_enforcement=False,
        )
    assert (tmp_path / "out" / "devin-cli.log").is_file()
    assert not (tmp_path / "out" / "execution.json").exists()


def test_verify_rejects_dirty_worktree(tmp_path: Path):
    spec = _mini_spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    (repo / "orphan.txt").write_text("uncommitted\n", encoding="utf-8")
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    adapter_log = write_adapter_log(runner / "adapter-log.jsonl", [mvnw_log_record()])
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    execution = ExecutionResult(
        run_id="run-dirty-verify",
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
        tests=[evidenced_test(name="ClienteServiceTest", log_file=log_file)],
        requirement_traceability={
            rf: ["src/main/java/ClienteService.java"],
            ac: ["tests/ClienteServiceTest.java"],
        },
        approved=True,
        adapter_log=str(adapter_log),
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "DIRTY_WORKTREE" for i in verify.issues)


def test_close_loop_after_adapter_writes_verify_report(tmp_path: Path):
    spec = _mini_spec()
    repo, base, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    out = tmp_path / "runs" / "rundevin01" / "executor"
    validations = tmp_path / "runs" / "rundevin01" / "validations"
    artifacts = tmp_path / "runs" / "rundevin01" / "artifacts"
    artifacts.mkdir(parents=True)

    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    out.mkdir(parents=True)
    (out / "mvnw-test.txt").write_text("ClienteServiceTest exit=0\n", encoding="utf-8")

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        root = Path(cwd or repo)
        write_files(root, DEFAULT_RESULT)
        pl = root / "docs" / "prompt-less"
        pl.mkdir(parents=True, exist_ok=True)
        (pl / "execution-result.json").write_text(
            json.dumps(
                {
                    "requirement_traceability": {
                        rf: ["src/main/java/ClienteService.java"],
                        ac: ["tests/ClienteServiceTest.java"],
                    },
                    "tests": [
                        {
                            "name": "ClienteServiceTest",
                            "passed": True,
                            "command": MVNW_TEST,
                            "exit_code": 0,
                            "timestamp": TEST_TS,
                            "log": "mvnw-test.txt",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    adapter = DevinAdapter(cli_bin="fake-devin", runner=runner)
    execution = adapter.execute(
        run_id="rundevin01",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out,
        layer="bff",
        prompt="impl",
        require_enforcement=False,
    )
    assert execution.tests
    assert execution.commands_executed

    spec_path = artifacts / "canonical-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    report = close_loop(
        spec_path=spec_path,
        result_path=out / "execution.json",
        repo_path=repo,
        adapter_log=out / "adapter-log.jsonl",
        out_dir=validations,
        layer="bff",
    )
    assert (validations / "verify-report.json").is_file()
    assert report["verify"]["status"] in {"passed", "needs_approval"}, report["verify"][
        "issues"
    ]
    assert report["execution"]["base_commit"] == base
    assert report["execution"]["result_commit"]


def test_devin_adapter_feeds_close_loop_cli_path(tmp_path: Path):
    """Script/CLI path: adapter → execution.json → close_loop → verify-report."""
    spec = _mini_spec()
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    run_dir = tmp_path / "runs" / "rundevin02"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    spec_path = artifacts / "canonical-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    out = run_dir / "executor"

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        return SimpleNamespace(returncode=0, stdout="noop\n", stderr="")

    adapter = DevinAdapter(cli_bin="fake-devin", runner=runner)
    adapter.execute(
        run_id="rundevin02",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out,
        layer="bff",
        prompt="noop",
        require_cli=False,
        require_enforcement=False,
    )
    report = close_loop(
        spec_path=spec_path,
        result_path=out / "execution.json",
        layer="bff",
        out_dir=run_dir / "validations",
        repo_path=repo,
        adapter_log=out / "adapter-log.jsonl",
    )
    assert (run_dir / "validations" / "verify-report.json").is_file()
    # sem mudança de código: verify pode passar ou só avisar NO_TESTS
    assert report["verify"]["status"] in {"passed", "failed", "needs_approval"}


@pytest.mark.skipif(
    os.environ.get("DEVIN_E2E") != "1",
    reason="e2e opcional: export DEVIN_E2E=1 com Devin CLI autenticado",
)
def test_devin_e2e_optional_live_cli(tmp_path: Path):
    import shutil

    if not shutil.which("devin"):
        pytest.skip("devin não está no PATH")
    repo, _, _ = make_git_repo(
        tmp_path,
        base_files={"README.md": "# e2e\n"},
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "Responda apenas OK sem alterar arquivos.\n",
        encoding="utf-8",
    )
    adapter = DevinAdapter(cli_bin="devin")
    result = adapter.execute(
        run_id="runde2e0001",
        repository="e2e-repo",
        repo_path=repo,
        out_dir=tmp_path / "out",
        prompt_file=prompt,
        timeout=120,
        auto_commit=True,
        require_enforcement=False,
    )
    assert result.base_commit
    assert result.result_commit
    assert (tmp_path / "out" / "execution.json").is_file()
    assert (tmp_path / "out" / "adapter-log.jsonl").is_file()
    assert (tmp_path / "out" / "devin-session.json").is_file()
