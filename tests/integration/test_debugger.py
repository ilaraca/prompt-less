"""Agent Debugger: failure / agent_behavior / harness_component / root_cause persistidos."""
from __future__ import annotations

import json
from pathlib import Path

from src.close_loop import close_loop
from src.domain.spec import CanonicalSpec
from src.executors.base import ExecutionResult
from src.executors.verify import verify_execution
from src.hardening.debugger import build_debugger_report
from src.runtime import RunContext, RunStore
from src.spec.builder import build_canonical_spec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXEC = FIXTURES / "executor"
_KEYS = ("failure", "agent_behavior", "harness_component", "root_cause")


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


def test_debugger_report_has_required_fields():
    spec = _mini_spec()
    result = ExecutionResult.from_dict(
        json.loads((EXEC / "execution_bad.json").read_text(encoding="utf-8"))
    )
    verify = verify_execution(result, spec, layer="bff")
    report = build_debugger_report(verify=verify, execution=result, stage="close_loop")
    for key in _KEYS:
        assert key in report and report[key], f"faltou {key}"
    assert report["failure"]["terminal_cause"]
    assert report["failure"]["codes"]
    assert report["harness_component"]["probable_owner"]
    assert report["root_cause"]["summary"]
    assert "não reportou" not in report["agent_behavior"]["implementation"] or result.changed_files


def test_close_loop_persists_debugger(tmp_path: Path):
    spec = _mini_spec()
    spec_path = tmp_path / "canonical-spec.yaml"
    import yaml

    spec_path.write_text(
        yaml.safe_dump(spec.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    data = json.loads((EXEC / "execution_bad.json").read_text(encoding="utf-8"))
    result_path = tmp_path / "execution.json"
    result_path.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    report = close_loop(spec_path=spec_path, result_path=result_path, out_dir=out)
    debug_path = out / "debugger.json"
    assert debug_path.is_file()
    persisted = json.loads(debug_path.read_text(encoding="utf-8"))
    for key in _KEYS:
        assert key in persisted
    assert report["debugger"]["failure"]["codes"]
    assert persisted["failure"]["terminal_cause"] == report["debugger"]["failure"]["terminal_cause"]


def test_run_store_write_debugger(tmp_path: Path):
    store = RunStore(
        RunContext.create(root=tmp_path, objective="historia", run_id="dbg-001")
    )
    store.bootstrap()
    payload = {
        "failure": {"terminal_cause": "test_failure", "symptom": "x", "codes": ["TEST_FAILED"]},
        "agent_behavior": {"implementation": "alterou 1 arquivo(s)", "verification": "falhou"},
        "harness_component": {"probable_owner": "implementation"},
        "root_cause": {"summary": "teste falhou no repositório"},
    }
    path = store.write_debugger(payload)
    assert path == tmp_path / "runs" / "dbg-001" / "validations" / "debugger.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    for key in _KEYS:
        assert key in loaded
