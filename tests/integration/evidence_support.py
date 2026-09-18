"""Helpers para montar um checkout Git + log de adapter nos testes do 20."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

TEST_TS = "2026-09-17T12:00:00+00:00"
MVNW_TEST = "./mvnw test"


def git_in(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Harness"
    env["GIT_AUTHOR_EMAIL"] = "harness@test"
    env["GIT_COMMITTER_NAME"] = "Harness"
    env["GIT_COMMITTER_EMAIL"] = "harness@test"
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=30,
    )
    return proc.stdout


def write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def make_git_repo(
    tmp_path: Path,
    *,
    base_files: dict[str, str],
    result_files: dict[str, str] | None = None,
    extra_result: dict[str, str] | None = None,
) -> tuple[Path, str, str]:
    """Cria repo com commit base e commit resultado; devolve (repo, base_sha, result_sha)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    git_in(repo, "config", "user.email", "harness@test")
    git_in(repo, "config", "user.name", "Harness")
    write_files(repo, base_files)
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-m", "base")
    base = git_in(repo, "rev-parse", "HEAD").strip()
    overlay = dict(result_files) if result_files is not None else dict(base_files)
    if extra_result:
        overlay.update(extra_result)
    if result_files is not None:
        # remove files that existed in base but not in the overlay
        for rel in list(base_files):
            if rel not in overlay:
                (repo / rel).unlink(missing_ok=True)
    write_files(repo, overlay)
    git_in(repo, "add", "-A")
    if git_in(repo, "status", "--porcelain").strip():
        git_in(repo, "commit", "-m", "result")
    result = git_in(repo, "rev-parse", "HEAD").strip()
    return repo, base, result


def write_adapter_log(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    path.write_text(body, encoding="utf-8")
    return path


def evidenced_test(
    *,
    name: str,
    log_file: Path,
    command: str = MVNW_TEST,
    exit_code: int = 0,
    passed: bool | None = None,
    timestamp: str = TEST_TS,
) -> dict[str, Any]:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if not log_file.exists():
        log_file.write_text(f"{name} exit={exit_code}\n", encoding="utf-8")
    return {
        "name": name,
        "passed": (exit_code == 0) if passed is None else passed,
        "command": command,
        "exit_code": exit_code,
        "timestamp": timestamp,
        "log": log_file.name,
    }


def mvnw_log_record(*, exit_code: int = 0, log: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "timestamp": TEST_TS,
        "command": MVNW_TEST,
        "exit_code": exit_code,
    }
    if log:
        rec["log"] = log
    return rec


DEFAULT_BASE = {
    "README.md": "# cliente\n",
}

DEFAULT_RESULT = {
    "README.md": "# cliente\n",
    "src/main/java/ClienteService.java": "class ClienteService {\n  void save() {}\n}\n",
    "tests/ClienteServiceTest.java": "class ClienteServiceTest {\n  void ok() {}\n}\n",
}
