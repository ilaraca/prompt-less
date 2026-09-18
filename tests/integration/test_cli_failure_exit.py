"""Exit code inequívoco da CLI e gate de consumo para o executor."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.runtime import RunNotReady, assert_run_ready_for_executor
from src.runtime.handlers import default_registry
from src.runtime.stage import HandlerRegistry, StageContext, StageError
from src.run import run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _cli_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PROMPTLESS_INTEGRITY_KEY"] = "test-integrity-key-not-for-prod"
    env["PWD"] = str(tmp_path)
    return env


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "src.run", *args],
        cwd=str(ROOT),
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )


def _registry_with_preprocess(handler) -> HandlerRegistry:
    reg = HandlerRegistry()
    src = default_registry()
    for name in src.names():
        if name != "preprocess":
            reg.register(name, src.get(name))
    reg.register("preprocess", handler)
    return reg


def test_cli_blocked_exits_nonzero_with_json(tmp_path: Path):
    proc = _run_cli(
        tmp_path,
        "historia",
        "--dry-run",
        "--no-split",
        "--run-id",
        "cli-blk-exit",
        "--inputs-dir",
        str(FIXTURES / "adversarial_injection"),
        "--output-root",
        str(tmp_path),
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert payload.get("reason") == "input_scan_failed"
    manifest = json.loads(
        (tmp_path / "runs" / "cli-blk-exit" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "blocked"
    assert (manifest.get("result_summary") or {}).get("reason") == "input_scan_failed"


def test_cli_success_exits_zero(tmp_path: Path):
    proc = _run_cli(
        tmp_path,
        "historia",
        "--dry-run",
        "--run-id",
        "cli-ok-exit",
        "--inputs-dir",
        str(FIXTURES / "happy_path"),
        "--output-root",
        str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "completed"
    manifest = json.loads(
        (tmp_path / "runs" / "cli-ok-exit" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "completed"


def test_cli_failed_exits_nonzero_with_json(tmp_path: Path):
    """Falha real (stage) → JSON legível + exit ≠ 0; manifesto failed + reason."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for src in (FIXTURES / "happy_path").iterdir():
        if src.is_file():
            shutil.copy2(src, inputs / src.name)

    def boom(_ctx: StageContext) -> None:
        raise RuntimeError("falha injetada no preprocess")

    with pytest.raises(StageError):
        run(
            "historia",
            dry_run=True,
            inputs_dir=inputs,
            output_root=tmp_path,
            run_id="cli-fail-seed",
            registry=_registry_with_preprocess(boom),
        )

    # Reproduz a falha via subprocess: resume com input adulterado → HashMismatch
    (inputs / "regras.yaml").write_text("fluxo: adulterado\n", encoding="utf-8")
    proc = _run_cli(
        tmp_path,
        "historia",
        "--dry-run",
        "--run-id",
        "cli-fail-seed",
        "--resume",
        "--inputs-dir",
        str(inputs),
        "--output-root",
        str(tmp_path),
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload.get("error_type") in {"HashMismatch", "StageError"}
    manifest = json.loads(
        (tmp_path / "runs" / "cli-fail-seed" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "failed"


def test_blocked_invalidates_mirror_and_blocks_executor(tmp_path: Path):
    # publica história completed primeiro
    ok = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="cli-ok-hist",
    )
    assert ok["status"] == "completed"
    historia = list((tmp_path / "outputs").rglob("historia.md"))
    assert historia, "espelho completed deve ter história"

    blocked = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "adversarial_injection",
        output_root=tmp_path,
        no_split=True,
        run_id="cli-blk-hist",
    )
    assert blocked["status"] == "blocked"
    mirror = json.loads(
        (tmp_path / "outputs" / ".mirror-manifest.json").read_text(encoding="utf-8")
    )
    assert mirror["run_id"] == "cli-blk-hist"
    assert mirror["status"] == "blocked"
    assert mirror.get("reason") == "input_scan_failed"
    # arquivos publicados pela run completed anterior foram podados
    assert not list((tmp_path / "outputs").rglob("historia.md"))

    with pytest.raises(RunNotReady) as exc_info:
        assert_run_ready_for_executor(
            Path(blocked["run_dir"]),
            run_id="cli-blk-hist",
            artifacts_dir=tmp_path / "outputs",
        )
    assert exc_info.value.status == "blocked"
    assert exc_info.value.reason == "input_scan_failed"

    # run_id de outra execução também é recusado
    with pytest.raises(RunNotReady, match="reutilização"):
        assert_run_ready_for_executor(
            Path(ok["run_dir"]),
            run_id="cli-blk-hist",
        )


def test_assert_ready_allows_completed(tmp_path: Path):
    result = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "happy_path",
        output_root=tmp_path,
        run_id="cli-ready-1",
    )
    manifest = assert_run_ready_for_executor(
        Path(result["run_dir"]),
        run_id="cli-ready-1",
        artifacts_dir=Path(result["run_dir"]) / "artifacts",
    )
    assert manifest["status"] == "completed"


def test_devin_cli_refuses_blocked_run(tmp_path: Path):
    blocked = run(
        "historia",
        dry_run=True,
        inputs_dir=FIXTURES / "adversarial_injection",
        output_root=tmp_path,
        no_split=True,
        run_id="devin-blk-1",
    )
    assert blocked["status"] == "blocked"
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / ".git").mkdir()
    proc = subprocess.run(
        [
            PYTHON,
            "-m",
            "src.executors.devin",
            "--repo",
            str(repo),
            "--run-id",
            "devin-blk-1",
            "--root",
            str(tmp_path),
            "--artifacts",
            str(Path(blocked["run_dir"]) / "artifacts"),
            "--no-cli",
        ],
        cwd=str(ROOT),
        env=_cli_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["error_type"] == "RunNotReady"
    assert payload["status"] == "blocked"
