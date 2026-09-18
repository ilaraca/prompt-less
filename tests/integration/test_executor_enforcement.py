"""37 — Limites efetivos do executor (EnforcedRunner + contrato externo)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.executors.devin import DevinAdapter
from src.executors.policy import (
    ENFORCEMENT_CAPABILITIES,
    load_profiles,
    normalize_limits,
    required_capabilities,
)
from src.executors.runner import (
    DEVIN_EXTERNAL_CONTRACT,
    DispatchBlocked,
    EnforcementContract,
    EnforcedRunner,
    LimitViolation,
    WriteDenied,
    assert_dispatch_allowed,
    local_enforcement_contract,
    probe_local_capabilities,
    scrub_credentials_env,
)
from src.executors.safe_exec import CommandDenied
from tests.integration.evidence_support import DEFAULT_BASE, make_git_repo, write_files


def _bff_profile(**limit_overrides: object) -> dict:
    profile = dict(load_profiles()["bff"])
    limits = dict(normalize_limits(profile))
    limits.update(limit_overrides)
    profile["limits"] = limits
    return profile


def test_profiles_declare_required_enforcement_limits():
    for layer, profile in load_profiles().items():
        limits = normalize_limits(profile)
        assert limits["network"] == "deny"
        assert limits["credentials"] == "scrub"
        assert required_capabilities(profile) == ENFORCEMENT_CAPABILITIES, layer


def test_authorized_task_end_to_end(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    log = tmp_path / "commands.jsonl"
    profile = _bff_profile()
    profile["commands_allow"] = [
        {"executable": "pytest"},
        {"executable": sys.executable},
        {"executable": "./mvnw", "args": ["test"]},
        {"executable": "git", "args": ["diff"]},
    ]

    with EnforcedRunner(profile, repo_root=repo, command_log=log) as runner:
        outcome = runner.run_authorized_task(
            writes={
                "src/widget.py": "VALUE = 42\n",
                "tests/check_widget.py": (
                    "from pathlib import Path\n"
                    "text = Path('src/widget.py').read_text()\n"
                    "assert 'VALUE = 42' in text\n"
                    "print('ok')\n"
                ),
            },
            commands=[[sys.executable, "tests/check_widget.py"]],
        )

    assert outcome["ok"] is True
    assert "src/widget.py" in outcome["writes"]
    assert (repo / "src" / "widget.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    lines = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines and lines[0]["enforced"] is True
    assert lines[0]["argv"][0] == sys.executable
    assert "ok" in outcome["commands"][0]["stdout"]


def test_denied_write_and_command_during_execution(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    profile = _bff_profile()
    profile["commands_allow"] = [{"executable": "pytest"}]

    with EnforcedRunner(profile, repo_root=repo, command_log=tmp_path / "log.jsonl") as runner:
        with pytest.raises(WriteDenied):
            runner.apply_write("infra/prod/deploy.yaml", "boom\n")
        with pytest.raises(WriteDenied):
            runner.apply_write(".github/workflows/ci.yml", "x\n")
        with pytest.raises(CommandDenied):
            runner.run(["terraform", "apply"])
        with pytest.raises(CommandDenied):
            runner.run(["curl", "https://example.com"])
        with pytest.raises(CommandDenied):
            runner.run(["pytest", "../../etc/passwd"])


def test_credentials_scrubbed_from_child_env(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    probe = repo / "tests" / "env_probe.py"
    probe.write_text(
        "import os, json\n"
        "print(json.dumps({\n"
        "  'aws': os.environ.get('AWS_SECRET_ACCESS_KEY'),\n"
        "  'tok': os.environ.get('MY_API_TOKEN'),\n"
        "  'keep': os.environ.get('PROMPTLESS_HARMLESS'),\n"
        "}))\n",
        encoding="utf-8",
    )
    profile = _bff_profile()
    profile["commands_allow"] = [{"executable": sys.executable}]
    os.environ["AWS_SECRET_ACCESS_KEY"] = "should-not-leak"
    os.environ["MY_API_TOKEN"] = "tok"
    os.environ["PROMPTLESS_HARMLESS"] = "keep-me"
    try:
        with EnforcedRunner(profile, repo_root=repo) as runner:
            proc = runner.run([sys.executable, "tests/env_probe.py"])
        data = json.loads((proc.stdout or "").strip())
        assert data["aws"] is None
        assert data["tok"] is None
        assert data["keep"] == "keep-me"
    finally:
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        os.environ.pop("MY_API_TOKEN", None)
        os.environ.pop("PROMPTLESS_HARMLESS", None)


def test_scrub_credentials_env_unit():
    cleaned = scrub_credentials_env(
        {
            "PATH": "/bin",
            "AWS_ACCESS_KEY_ID": "AKIAxxx",
            "OPENAI_API_KEY": "sk",
            "HOME": "/tmp",
        }
    )
    assert cleaned["PATH"] == "/bin"
    assert cleaned["HOME"] == "/tmp"
    assert "AWS_ACCESS_KEY_ID" not in cleaned
    assert "OPENAI_API_KEY" not in cleaned


def test_network_denied_for_python_child(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "net_probe.py").write_text(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=1)\n"
        "    print('OPEN')\n"
        "except OSError as e:\n"
        "    print('DENIED:' + type(e).__name__)\n",
        encoding="utf-8",
    )
    profile = _bff_profile(network="deny")
    profile["commands_allow"] = [{"executable": sys.executable}]
    with EnforcedRunner(profile, repo_root=repo) as runner:
        proc = runner.run([sys.executable, "tests/net_probe.py"])
    assert "DENIED" in (proc.stdout or "")
    assert "OPEN" not in (proc.stdout or "")


def test_timeout_enforced(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "sleep.py").write_text(
        "import time\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    profile = _bff_profile(timeout_seconds=0.3)
    profile["commands_allow"] = [{"executable": sys.executable}]
    with EnforcedRunner(profile, repo_root=repo) as runner:
        with pytest.raises(LimitViolation, match="timeout"):
            runner.run([sys.executable, "tests/sleep.py"])


def test_dispatch_blocked_without_capabilities():
    profile = _bff_profile()
    with pytest.raises(DispatchBlocked) as exc:
        assert_dispatch_allowed(profile, frozenset({"commands", "writes"}))
    assert "network" in exc.value.missing
    assert "credentials" in exc.value.missing


def test_devin_external_default_contract_blocks_dispatch(tmp_path: Path):
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    adapter = DevinAdapter(
        cli_bin="fake-devin",
        runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        enforcement_contract=DEVIN_EXTERNAL_CONTRACT,
    )
    with pytest.raises(DispatchBlocked):
        adapter.execute(
            run_id="run-block",
            repository="bff-cliente",
            repo_path=repo,
            out_dir=tmp_path / "out",
            layer="bff",
            prompt="x",
            require_enforcement=True,
        )


def test_devin_dispatch_with_attested_contract(tmp_path: Path):
    repo, base, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    contract = local_enforcement_contract()
    assert contract.capabilities() >= ENFORCEMENT_CAPABILITIES

    def runner(argv, profile=None, cwd=None, timeout=None, **kwargs):
        write_files(Path(cwd or repo), {"src/main/java/ClienteService.java": "class C {}\n"})
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    adapter = DevinAdapter(
        cli_bin="fake-devin",
        runner=runner,
        enforcement_contract=contract,
    )
    result = adapter.execute(
        run_id="run-ok-enforce",
        repository="bff-cliente",
        repo_path=repo,
        out_dir=tmp_path / "out",
        layer="bff",
        prompt="impl",
        require_enforcement=True,
    )
    assert result.base_commit == base
    session = json.loads(
        (tmp_path / "out" / "devin-session.json").read_text(encoding="utf-8")
    )
    assert session["enforcement"]["adapter_id"] == "enforced-runner"
    assert (tmp_path / "out" / "enforcement-contract.json").is_file()
    evidence = session["enforcement"]["evidence"]
    assert "commands" in evidence and "network" in evidence


def test_devin_blocks_without_layer_when_enforcement_required(tmp_path: Path):
    repo, _, _ = make_git_repo(tmp_path, base_files=DEFAULT_BASE)
    adapter = DevinAdapter(
        cli_bin="fake-devin",
        runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
        enforcement_contract=local_enforcement_contract(),
    )
    with pytest.raises(DispatchBlocked, match="layer/profile"):
        adapter.execute(
            run_id="run-nolayer",
            repository="bff-cliente",
            repo_path=repo,
            out_dir=tmp_path / "out",
            prompt="x",
            require_enforcement=True,
        )


def test_local_capabilities_cover_defaults():
    caps = probe_local_capabilities()
    assert {"commands", "writes", "credentials", "time", "network"} <= caps
    contract = local_enforcement_contract()
    assert_dispatch_allowed(_bff_profile(), contract.capabilities())


def test_enforcement_contract_roundtrip():
    raw = {
        "adapter_id": "vendor-sandbox",
        "guarantees": {name: True for name in ENFORCEMENT_CAPABILITIES},
        "evidence": {name: f"vendor/{name}" for name in ENFORCEMENT_CAPABILITIES},
        "notes": "attested",
    }
    c = EnforcementContract.from_dict(raw)
    assert c.capabilities() == ENFORCEMENT_CAPABILITIES
    assert c.to_dict()["notes"] == "attested"
