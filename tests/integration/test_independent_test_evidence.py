"""35 — evidência de teste independente do relato do agente."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.executors.devin import DevinAdapter
from src.executors.evidence import (
    HARNESS_EXECUTED_BY,
    make_evidence_binding,
    spec_content_hash,
)
from src.executors.verify import verify_execution

from tests.integration.evidence_support import (
    DEFAULT_BASE,
    DEFAULT_RESULT,
    MVNW_TEST,
    evidenced_test,
    make_git_repo,
    mvnw_log_record,
    write_adapter_log,
    write_files,
)
from tests.integration.test_evidence_verify import _harness_test, _result, _spec


def test_passed_true_alone_never_sufficient(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    adapter_log = write_adapter_log(tmp_path / "adapter-log.jsonl", [])
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=list(DEFAULT_RESULT),
        tests=[{"name": "ghost", "passed": True}],
    )
    verify = verify_execution(
        execution, spec, layer="bff", repo_path=repo, adapter_log=adapter_log
    )
    assert verify.status == "failed"
    assert any(i.code == "TEST_NOT_EVIDENCED" for i in verify.issues)
    assert any("passed=True do agente não basta" in i.message for i in verify.issues)


def test_missing_incomplete_tampered_other_run_log_fail(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    test, rec = _harness_test(spec, log_file=log_file, base=base, result=result_sha)

    # Ausente
    missing = _result(
        spec,
        base=base,
        result=result_sha,
        changed=list(DEFAULT_RESULT),
        tests=[{**test, "log": "missing-log.txt"}],
    )
    v_missing = verify_execution(
        missing,
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "a.jsonl", [rec]),
    )
    assert any(i.code == "TEST_NOT_EVIDENCED" for i in v_missing.issues)

    # Incompleto (vazio)
    empty = runner / "empty.log"
    empty.write_text("", encoding="utf-8")
    incomplete = {**test, "log": empty.name, "log_sha256": None}
    rec_empty = {**rec, "log": empty.name, "log_sha256": None}
    v_empty = verify_execution(
        _result(
            spec,
            base=base,
            result=result_sha,
            changed=list(DEFAULT_RESULT),
            tests=[incomplete],
        ),
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "b.jsonl", [rec_empty]),
    )
    assert any("incompleto" in i.message for i in v_empty.issues)

    # Adulterado
    tampered_body = log_file.read_text(encoding="utf-8") + "\n# forged\n"
    log_file.write_text(tampered_body, encoding="utf-8")
    v_tamp = verify_execution(
        _result(
            spec,
            base=base,
            result=result_sha,
            changed=list(DEFAULT_RESULT),
            tests=[test],
        ),
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "c.jsonl", [rec]),
    )
    assert any(i.code == "TEST_EVIDENCE_TAMPERED" for i in v_tamp.issues)

    # Outra run
    other_bind = make_evidence_binding(
        run_id="run-OTHER",
        repository="bff-cliente",
        base_commit=base,
        result_commit=result_sha,
        spec_hash=spec_content_hash(spec),
    )
    other_test = {**test, "binding": other_bind, "run_id": "run-OTHER"}
    # regenera log limpo para não misturar com adulteração
    log_file.write_text("ok\n", encoding="utf-8")
    other_test = evidenced_test(
        name="ClienteServiceTest",
        log_file=log_file,
        covers=[spec.acceptance_criteria[0].id],
        binding=other_bind,
    )
    other_rec = mvnw_log_record(
        log=log_file.name,
        binding=other_bind,
        log_sha256=other_test["log_sha256"],
    )
    v_other = verify_execution(
        _result(
            spec,
            base=base,
            result=result_sha,
            changed=list(DEFAULT_RESULT),
            tests=[other_test],
            run_id="run-ev-001",
        ),
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "d.jsonl", [other_rec]),
    )
    assert any(
        i.code in {"TEST_EVIDENCE_BINDING", "TEST_EVIDENCE_OTHER_RUN"}
        for i in v_other.issues
    )


def test_mandatory_ac_file_existence_insufficient(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    log_file = runner / "mvnw-test.txt"
    # Teste harness OK mas NÃO cobre o AC; locator de arquivo existe.
    test, rec = _harness_test(
        spec,
        log_file=log_file,
        base=base,
        result=result_sha,
        covers=[],  # sem covers explícito
        name="UnrelatedSuite",
    )
    # Força locator que não casa com o nome do teste
    ac = spec.acceptance_criteria[0].id
    rf = spec.requirements[0].id
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=list(DEFAULT_RESULT),
        tests=[test],
        trace={
            rf: ["src/main/java/ClienteService.java"],
            ac: ["tests/ClienteServiceTest.java"],
        },
    )
    verify = verify_execution(
        execution,
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "adapter-log.jsonl", [rec]),
    )
    assert verify.status == "failed"
    assert any(i.code == "AC_WITHOUT_BEHAVIORAL_EVIDENCE" for i in verify.issues)


def test_known_failure_then_real_fix_rerun(tmp_path: Path):
    spec = _spec()
    repo, base, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    out = tmp_path / "executor"
    state = {"exit": 1}

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        if argv and argv[0] in {"devin", "fake-devin"}:
            write_files(Path(cwd or repo), DEFAULT_RESULT)
            pl = Path(cwd or repo) / "docs" / "prompt-less"
            pl.mkdir(parents=True, exist_ok=True)
            (pl / "execution-result.json").write_text(
                json.dumps(
                    {
                        "requirement_traceability": {
                            spec.requirements[0].id: [
                                "src/main/java/ClienteService.java"
                            ],
                            spec.acceptance_criteria[0].id: [
                                "tests/ClienteServiceTest.java"
                            ],
                        },
                        "tests": [
                            {
                                "name": "ClienteServiceTest",
                                "passed": True,  # agente mente — harness ignora
                                "command": MVNW_TEST,
                                "kind": "unit",
                                "covers": [spec.acceptance_criteria[0].id],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="devin\n", stderr="")
        # comando de teste sugerido
        return SimpleNamespace(
            returncode=state["exit"],
            stdout="fail\n" if state["exit"] else "ok\n",
            stderr="",
        )

    adapter = DevinAdapter(cli_bin="fake-devin", runner=runner)
    first = adapter.execute(
        run_id="run-fix-1",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out / "1",
        layer="bff",
        prompt="impl",
        require_cli=False,
        spec_hash=spec_content_hash(spec),
    )
    assert first.tests
    assert first.tests[0]["executed_by"] == HARNESS_EXECUTED_BY
    assert first.tests[0]["exit_code"] == 1
    assert first.tests[0]["passed"] is False
    v1 = verify_execution(
        first,
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=out / "1" / "adapter-log.jsonl",
    )
    assert any(i.code == "TEST_FAILED" for i in v1.issues)

    state["exit"] = 0
    # Novo commit base limpo: worktree já commitado; reexecuta sobre HEAD atual
    second = adapter.execute(
        run_id="run-fix-2",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out / "2",
        layer="bff",
        prompt="impl",
        require_cli=False,
        invoke_cli=True,
        spec_hash=spec_content_hash(spec),
    )
    # Sem mudanças Git → auto_commit pode não criar commit novo; ok se HEAD estável
    assert second.tests[0]["exit_code"] == 0
    assert second.tests[0]["passed"] is True
    v2 = verify_execution(
        second,
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=out / "2" / "adapter-log.jsonl",
    )
    assert v2.status == "passed", [i.to_dict() for i in v2.issues]


def test_e2e_recorded_separately_from_stubs_skips(tmp_path: Path):
    spec = _spec()
    repo, base, result_sha = make_git_repo(
        tmp_path, base_files=DEFAULT_BASE, extra_result=DEFAULT_RESULT
    )
    runner = tmp_path / "runner"
    e2e_log = runner / "e2e.log"
    stub = {
        "name": "skipped-case",
        "kind": "skip",
        "passed": False,
        "suggestion_only": True,
        "executed_by": None,
        "covers": [spec.acceptance_criteria[0].id],
    }
    e2e, rec = _harness_test(
        spec,
        log_file=e2e_log,
        base=base,
        result=result_sha,
        name="ClienteServiceTest",
        kind="e2e",
    )
    execution = _result(
        spec,
        base=base,
        result=result_sha,
        changed=[
            "src/main/java/ClienteService.java",
            "tests/ClienteServiceTest.java",
        ],
        tests=[e2e, stub],
    )
    verify = verify_execution(
        execution,
        spec,
        layer="bff",
        repo_path=repo,
        adapter_log=write_adapter_log(runner / "adapter-log.jsonl", [rec]),
    )
    assert verify.status == "passed", [i.to_dict() for i in verify.issues]
    kinds = verify.evidence_hashes["test_kinds"]
    assert "ClienteServiceTest" in kinds["e2e"]
    assert "skipped-case" in kinds["stub_or_skip"]
    assert "ClienteServiceTest" not in kinds["stub_or_skip"]


def test_materialize_ignores_sidecar_passed_without_running(tmp_path: Path):
    """passed=True no sidecar não materializa exit_code=0 sem o runner."""
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    out = tmp_path / "out"
    calls: list[list[str]] = []

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        calls.append(list(argv))
        if argv and argv[0] in {"fake-devin", "devin"}:
            write_files(Path(cwd or repo), DEFAULT_RESULT)
            pl = Path(cwd or repo) / "docs" / "prompt-less"
            pl.mkdir(parents=True, exist_ok=True)
            (pl / "execution-result.json").write_text(
                json.dumps(
                    {
                        "tests": [
                            {
                                "name": "only-passed",
                                "passed": True,
                                # sem command — não pode inventar exit 0
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    adapter = DevinAdapter(cli_bin="fake-devin", runner=runner)
    result = adapter.execute(
        run_id="run-no-cmd",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=out,
        layer="bff",
        prompt="x",
        require_cli=False,
    )
    assert result.tests
    assert result.tests[0].get("suggestion_only") is True
    assert "exit_code" not in result.tests[0] or result.tests[0].get("passed") is False
    assert result.tests[0].get("executed_by") is None
    # Nenhum comando de teste foi executado — só o CLI Devin
    assert all(c[0] in {"fake-devin", "devin"} for c in calls)
