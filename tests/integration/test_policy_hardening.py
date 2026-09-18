"""Policy §5: realpath/symlink, profiles extra, allowlist semântica, shell=False."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.executors.policy import (
    KNOWN_LAYERS,
    check_command_allowed,
    check_write_allowed,
    load_profiles,
    parse_command,
    resolve_repo_path,
)
from src.executors.safe_exec import CommandDenied, ShellForbidden, run_argv
from src.executors.verify import verify_execution
from src.spec.builder import build_canonical_spec
from src.executors.base import ExecutionResult

ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = ROOT / "config" / "permission_profiles.yaml"


def test_all_known_layers_have_explicit_profiles():
    profiles = load_profiles()
    for layer in KNOWN_LAYERS:
        assert layer in profiles, f"profile ausente: {layer}"
        assert profiles[layer].get("commands_allow")
        assert profiles[layer].get("write_allow")
    raw = yaml.safe_load(PROFILES_PATH.read_text(encoding="utf-8"))
    assert set(raw["profiles"]) >= set(KNOWN_LAYERS)


def test_unknown_layer_still_fail_closed():
    spec = build_canonical_spec(
        ui={"actions": [{"id": "a", "method": "POST", "path": "/x"}]},
        regras={"bloqueios": [{"trigger": "x", "status": 400}]},
        claims=[
            {
                "id": "CLM-1",
                "text": "x 400",
                "origin": "declared",
                "confidence": 1.0,
                "sources": [{"document": "r.yaml"}],
            }
        ],
        servico={"id": "ms-x", "repos": ["processador-pagamentos"]},
    )
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


@pytest.mark.parametrize("layer", ["gtw", "worker", "batch"])
def test_new_profiles_allow_in_scope_and_deny_prod(layer: str):
    profile = load_profiles()[layer]
    assert check_write_allowed("src/Foo.java", profile)
    assert check_command_allowed("./mvnw test", profile)
    assert not check_write_allowed("infra/prod/deploy.yaml", profile)
    assert not check_command_allowed("terraform apply", profile)


def test_realpath_symlink_escape_denied(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pem").write_text("k", encoding="utf-8")
    leak = repo / "src" / "leak"
    leak.symlink_to(outside)
    profile = load_profiles()["bff"]
    assert resolve_repo_path("src/leak/secret.pem", repo) is None
    assert not check_write_allowed("src/leak/secret.pem", profile, repo_root=repo)
    assert check_write_allowed("src/Foo.java", profile, repo_root=repo)
    assert resolve_repo_path("src/Foo.java", repo) == "src/Foo.java"


def test_semantic_allowlist_rejects_token_prefix_and_escaped_path(tmp_path: Path):
    bff = load_profiles()["bff"]
    assert check_command_allowed("./mvnw test", bff)
    assert not check_command_allowed("./mvnw test-compile", bff)
    assert not check_command_allowed("./mvnw test && terraform apply", bff)
    assert not check_command_allowed("pytest --out=/etc/passwd", bff)
    assert not check_command_allowed("pytest ../../secret.env", bff)
    assert check_command_allowed("pytest tests/unit", bff)
    assert check_command_allowed({"executable": "pytest", "args": ["-q"]}, bff)
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    assert check_command_allowed("pytest tests/unit", bff, repo_root=repo)
    assert not check_command_allowed("pytest /etc/passwd", bff, repo_root=repo)


def test_parse_command_dict_rejects_shell_meta_in_args():
    assert parse_command({"executable": "pytest", "args": ["-q;id"]}) is None
    assert parse_command({"executable": "pytest", "args": ["-q"]}) == ["pytest", "-q"]


def test_run_argv_never_uses_shell():
    import sys

    bff = load_profiles()["bff"]
    with pytest.raises(ShellForbidden):
        run_argv(["pytest"], bff, shell=True)
    with pytest.raises(CommandDenied):
        run_argv(["terraform", "apply"], bff)
    proc = run_argv(
        [sys.executable, "-c", "print('ok')"],
        profile=None,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "ok" in (proc.stdout or "")


def test_src_has_no_shell_true():
    import re

    offenders = []
    call_re = re.compile(r"subprocess\.\w+\([\s\S]{0,400}?shell\s*=\s*True")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if call_re.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
