"""Ciclo executor: verify, policy, approval e reparo."""
from __future__ import annotations

import json
from pathlib import Path

from src.close_loop import close_loop
from src.domain.spec import AcceptanceCriterion, CanonicalSpec, Requirement
from src.executors import DevinAdapter, build_repair_request, verify_execution
from src.executors.base import ExecutionResult
from src.executors.policy import check_command_allowed, check_write_allowed, load_profiles
from src.spec.builder import build_canonical_spec

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


def test_verify_passes_good_execution():
    spec = _mini_spec()
    data = json.loads((EXEC / "execution_ok.json").read_text(encoding="utf-8"))
    # alinhar IDs do fixture aos do spec
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    data["requirement_traceability"] = {
        rf: ["src/main/java/ClienteService.java"],
        ac: ["tests/ClienteServiceTest.java"],
    }
    result = ExecutionResult.from_dict(data)
    verify = verify_execution(result, spec, layer="bff")
    assert verify.status == "passed"
    assert not verify.has_errors


def test_verify_fails_out_of_scope_and_unmapped():
    spec = _mini_spec()
    result = ExecutionResult.from_dict(
        json.loads((EXEC / "execution_bad.json").read_text(encoding="utf-8"))
    )
    verify = verify_execution(result, spec, layer="bff")
    assert verify.status == "failed"
    codes = {i.code for i in verify.issues}
    assert "FILE_OUT_OF_SCOPE" in codes
    assert "COMMAND_DENIED" in codes
    assert "TEST_FAILED" in codes
    assert "RF_NOT_MAPPED" in codes


def test_verify_no_tests_is_error_for_code_change():
    spec = _mini_spec()
    result = ExecutionResult(
        run_id="r",
        agent="devin",
        repository="bff-cliente",
        layer="bff",
        changed_files=["src/main/java/Foo.java"],
        commands_executed=["./mvnw test"],
        tests=[],
        requirement_traceability={
            spec.requirements[0].id: ["src/main/java/Foo.java"],
            spec.acceptance_criteria[0].id: ["src/main/java/Foo.java"],
        },
        approved=True,
    )
    verify = verify_execution(result, spec, layer="bff")
    assert verify.status == "failed"
    assert any(i.code == "NO_TESTS_REPORTED" and i.severity == "error" for i in verify.issues)


def test_needs_approval_gate():
    spec = _mini_spec()
    data = json.loads((EXEC / "execution_needs_approval.json").read_text(encoding="utf-8"))
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    data["requirement_traceability"] = {
        rf: data["changed_files"][:1],
        ac: data["changed_files"][1:],
    }
    result = ExecutionResult.from_dict(data)
    verify = verify_execution(result, spec, layer="bff")
    assert verify.status == "needs_approval"


def test_repair_request_requires_approval():
    spec = _mini_spec()
    result = ExecutionResult.from_dict(
        json.loads((EXEC / "execution_bad.json").read_text(encoding="utf-8"))
    )
    verify = verify_execution(result, spec, layer="bff")
    repair = build_repair_request(verify, result, attempt=1)
    assert repair is not None
    assert repair["status"] == "repair_requested"
    assert repair["requires_approval"] is True
    assert "infra/prod/deploy.yaml" in repair["required_reverts"]
    assert ".github/workflows/deploy.yml" in repair["required_reverts"]
    assert "infra/prod/deploy.yaml" not in repair["editable_surface"]
    assert "RF-001" not in repair["editable_surface"]
    exhausted = build_repair_request(verify, result, attempt=3)
    assert exhausted["status"] == "exhausted"


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


def test_close_loop_approve_passes(tmp_path: Path):
    spec = _mini_spec()
    spec_path = tmp_path / "canonical-spec.yaml"
    import yaml

    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # result with matching IDs
    data = json.loads((EXEC / "execution_needs_approval.json").read_text(encoding="utf-8"))
    rf = spec.requirements[0].id
    ac = spec.acceptance_criteria[0].id
    data["requirement_traceability"] = {
        rf: ["src/main/java/ClienteService.java"],
        ac: ["tests/T.java"],
    }
    result_path = tmp_path / "execution.json"
    result_path.write_text(json.dumps(data), encoding="utf-8")

    blocked = close_loop(spec_path=spec_path, result_path=result_path, approve=False)
    assert blocked["verify"]["status"] == "needs_approval"

    ok = close_loop(spec_path=spec_path, result_path=result_path, approve=True)
    assert ok["verify"]["status"] == "passed"
