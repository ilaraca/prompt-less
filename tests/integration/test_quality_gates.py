"""Gates de produção: lock, pins, cobertura, YAML e testes adversariais."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.quality_gates import GATE_NAMES, gate_commands

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ACTION_RE = re.compile(
    r"^(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<sha>[0-9a-f]{40})$"
)
SUPPORTED_PYTHON = ["3.10", "3.11", "3.12", "3.13"]
ADVERSARIAL_TESTS = (
    "tests/integration/test_evidence_verify.py",
    "tests/integration/test_independent_test_evidence.py",
    "tests/integration/test_contextual_provenance.py",
    "tests/integration/test_safe_run_storage.py",
    "tests/integration/test_runtime_isolation.py",
    "tests/integration/test_executor_loop.py",
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_lockfiles_exist_and_are_hashed():
    runtime = ROOT / "requirements.lock"
    dev = ROOT / "requirements-dev.lock"
    assert runtime.is_file(), "requirements.lock ausente"
    assert dev.is_file(), "requirements-dev.lock ausente"
    runtime_text = runtime.read_text(encoding="utf-8").lower()
    dev_text = dev.read_text(encoding="utf-8").lower()
    assert "--hash=sha256:" in runtime_text
    assert "--hash=sha256:" in dev_text
    assert "pyyaml" in runtime_text
    assert "pytest" in dev_text
    assert "ruff" in dev_text
    assert "mypy" in dev_text
    assert "pip-audit" in dev_text
    assert "detect-secrets" in dev_text
    assert "exceptiongroup==" in dev_text


def test_ci_has_minimal_permissions_and_sha_pinned_actions():
    doc = _workflow()
    perms = doc.get("permissions") or {}
    assert perms.get("contents") == "read"
    extra = {k: v for k, v in perms.items() if k != "contents"}
    assert extra == {}, extra

    uses: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if "uses" in step:
                uses.append(step["uses"])
    assert uses, "workflow sem actions"
    for spec in uses:
        match = ACTION_RE.match(spec)
        assert match, f"action não pinada por SHA: {spec}"
        assert SHA_RE.match(match.group("sha"))
        assert "@v" not in spec


def test_ci_python_matrix_matches_supported_versions():
    doc = _workflow()
    matrix = (
        doc["jobs"]["quality-gates"]["strategy"]["matrix"]["python-version"]
    )
    assert matrix == SUPPORTED_PYTHON


def test_ci_invoca_o_mesmo_script_local():
    """O YAML não lista mypy/ruff — senão o gate local volta a divergir."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/quality_gates.py" in text
    assert "scripts/ci_reports.py collect" in text
    assert "actions/upload-artifact@" in text
    assert "--ignore-vuln" not in text
    assert "mypy src" not in text
    assert "ruff check" not in text


def test_gate_local_inclui_compile_ruff_mypy_pytest():
    names = [name for name, _ in gate_commands(ROOT / "reports")]
    for required in GATE_NAMES:
        assert required in names, required
    joined = " ".join(" ".join(argv) for _, argv in gate_commands(ROOT / "reports"))
    for needle in (
        "compileall",
        "mypy",
        "ruff",
        "pytest",
        "--cov-fail-under=70",
        "validate-yaml",
        "yamllint",
    ):
        assert needle in joined, needle
    assert "pip-audit" in joined or "pip_audit" in joined
    assert "detect-secrets" in joined or "detect_secrets" in joined


def test_modulos_novos_nao_entram_no_override_mypy():
    """Corrigir tipo no slice, não silenciar o módulo no pyproject."""
    text = PYPROJECT.read_text(encoding="utf-8")
    for module in ("src.planning", "src.renderers.sdd", "src.validators", "src.learning"):
        assert f'"{module}"' not in text, module


def test_ci_aggregator_job_is_required_ready():
    doc = _workflow()
    ci = doc["jobs"]["ci"]
    assert ci["name"] == "CI"
    assert ci["needs"] == "quality-gates" or ci["needs"] == ["quality-gates"]
    run_steps = " ".join(
        step.get("run") or "" for step in ci.get("steps") or []
    )
    assert "needs.quality-gates.result" in run_steps


def test_adversarial_runtime_policy_provenance_tests_are_collected():
    skip_re = re.compile(r"pytest\.mark\.(skip|skipif|xfail)")
    collected = []
    for rel in ADVERSARIAL_TESTS:
        path = ROOT / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert not skip_re.search(text), rel
        names = re.findall(r"^def (test_\w+)", text, re.M)
        assert names, rel
        collected.extend(names)
    assert "test_forged_payload_cannot_hide_out_of_scope_file" in collected
    assert "test_adulteracao_de_evento_e_detectada" in collected
    assert "test_run_com_run_id_de_traversal_nao_escreve_fora" in collected
    assert "test_policy_rejects_path_traversal" in collected
    assert "test_two_runs_do_not_overwrite_state" in collected


def test_yaml_configs_safe_load():
    from scripts.ci_reports import validate_yaml

    errors = validate_yaml(ROOT)
    assert errors == [], errors
