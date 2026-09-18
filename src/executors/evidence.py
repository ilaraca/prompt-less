"""Evidência real da execução: Git, log do adapter e artefatos de teste.

O payload do executor é relato. Este módulo consulta o repositório e os
logs estruturados e devolve o que de fato ocorreu — fail-closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.executors.policy import normalize_repo_path, parse_command
from src.runtime.atomic_io import UnsafePath, resolve_within, sha256_of
from src.runtime.integrity import (
    MissingIntegrityKey,
    current_kid,
    seal_hmac,
)

_GIT_TIMEOUT = 30
_UNSIGNED_HASH_FIELDS = frozenset({"hmac"})


class GitEvidenceError(RuntimeError):
    """Falha ao inspecionar o repositório Git."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class GitInspection:
    ok: bool
    issues: list[tuple[str, str]] = field(default_factory=list)
    base_sha: str | None = None
    result_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    diff_raw: str = ""


@dataclass
class AdapterLog:
    ok: bool
    issues: list[tuple[str, str]] = field(default_factory=list)
    path: Path | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    commands: list[str | dict[str, Any]] = field(default_factory=list)
    sha256: str | None = None


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_AUTHOR_NAME", "prompt-less")
    env.setdefault("GIT_AUTHOR_EMAIL", "prompt-less@test")
    env.setdefault("GIT_COMMITTER_NAME", "prompt-less")
    env.setdefault("GIT_COMMITTER_EMAIL", "prompt-less@test")
    return env


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        env=_git_env(),
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise GitEvidenceError(
            "GIT_COMMAND_FAILED",
            f"git {' '.join(args)} falhou: {detail}",
        )
    return proc


def canonical_json_hash(payload: Any) -> str:
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def resolve_git_repo(repo: Path) -> Path:
    repo = Path(repo)
    if not repo.exists():
        raise GitEvidenceError("MISSING_REPO_EVIDENCE", f"repositório inexistente: {repo}")
    proc = run_git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise GitEvidenceError(
            "MISSING_REPO_EVIDENCE",
            f"caminho não é um work tree Git: {repo}",
        )
    common = run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (repo / common_path).resolve()
    else:
        common_path = common_path.resolve()
    if not common_path.exists():
        raise GitEvidenceError("MISSING_REPO_EVIDENCE", f"git dir ausente: {common_path}")
    return repo.resolve()


def full_commit_sha(repo: Path, rev: str) -> str | None:
    if not rev or not str(rev).strip():
        return None
    proc = run_git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}", check=False
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def inspect_commits(repo: Path, base_commit: str, result_commit: str) -> GitInspection:
    """Confirma ancestralidade, mesmo repositório e calcula o diff real."""
    issues: list[tuple[str, str]] = []
    try:
        repo = resolve_git_repo(repo)
    except GitEvidenceError as exc:
        return GitInspection(ok=False, issues=[(exc.code, str(exc))])

    base_sha = full_commit_sha(repo, base_commit)
    result_sha = full_commit_sha(repo, result_commit)
    if not base_sha:
        issues.append(
            (
                "COMMIT_NOT_IN_REPO",
                f"base_commit `{base_commit}` não existe neste repositório",
            )
        )
    if not result_sha:
        issues.append(
            (
                "COMMIT_NOT_IN_REPO",
                f"result_commit `{result_commit}` não existe neste repositório",
            )
        )
    if issues:
        return GitInspection(ok=False, issues=issues, base_sha=base_sha, result_sha=result_sha)

    assert base_sha is not None and result_sha is not None
    ancestor = run_git(
        repo, "merge-base", "--is-ancestor", base_sha, result_sha, check=False
    )
    if ancestor.returncode != 0:
        issues.append(
            (
                "COMMIT_NOT_ANCESTOR",
                f"`{base_sha}` não é ancestral de `{result_sha}` no mesmo repositório",
            )
        )
        return GitInspection(
            ok=False,
            issues=issues,
            base_sha=base_sha,
            result_sha=result_sha,
        )

    names = run_git(
        repo,
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        base_sha,
        result_sha,
    )
    changed = [p for p in names.stdout.split("\0") if p]
    diff_raw = run_git(
        repo, "diff", "--raw", "--no-renames", base_sha, result_sha
    ).stdout
    return GitInspection(
        ok=True,
        base_sha=base_sha,
        result_sha=result_sha,
        changed_files=changed,
        diff_raw=diff_raw,
    )


def git_file_exists(repo: Path, commit: str, path: str) -> bool:
    norm = normalize_repo_path(path)
    if norm is None:
        return False
    proc = run_git(repo, "cat-file", "-e", f"{commit}:{norm}", check=False)
    return proc.returncode == 0


def git_file_line_count(repo: Path, commit: str, path: str) -> int | None:
    norm = normalize_repo_path(path)
    if norm is None:
        return None
    proc = run_git(repo, "show", f"{commit}:{norm}", check=False)
    if proc.returncode != 0:
        return None
    text = proc.stdout
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def git_symlink_target(repo: Path, commit: str, path: str) -> str | None:
    """Alvo do symlink no commit, ou None se não for symlink / falhar."""
    norm = normalize_repo_path(path)
    if norm is None:
        return None
    proc = run_git(repo, "ls-tree", "-z", commit, "--", norm, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return None
    entry = proc.stdout.split("\0", 1)[0]
    if not entry.startswith("120000 "):
        return None
    shown = run_git(repo, "show", f"{commit}:{norm}", check=False)
    if shown.returncode != 0:
        return None
    target = shown.stdout.strip()
    return target or None


def realpath_in_repo(repo: Path, path: str) -> str | None:
    """Caminho relativo canônico após resolver symlinks; None se escapar."""
    norm = normalize_repo_path(path)
    if norm is None:
        return None
    repo = Path(repo).resolve()
    try:
        resolved = resolve_within(repo, repo / norm)
    except UnsafePath:
        return None
    try:
        rel = resolved.relative_to(repo)
    except ValueError:
        return None
    return rel.as_posix()


def resolve_symlink_target_path(link_path: str, target: str) -> str | None:
    """Resolve alvo relativo ao path do link, ainda dentro do repo."""
    link_norm = normalize_repo_path(link_path)
    if link_norm is None:
        return None
    raw = target.strip().replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("//"):
        return None
    parent = str(Path(link_norm).parent).replace("\\", "/")
    if parent in {".", ""}:
        joined = raw
    else:
        joined = f"{parent}/{raw}"
    parts: list[str] = []
    for part in joined.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return None
    return normalize_repo_path("/".join(parts))


@dataclass
class PolicyPathSet:
    paths: list[str]
    escaped: bool = False


def policy_paths_for(repo: Path, commit: str, git_path: str) -> PolicyPathSet:
    """Paths a avaliar na policy: path Git + realpath + alvo de symlink."""
    seen: list[str] = []
    escaped = False

    def _add(value: str | None) -> None:
        if value and value not in seen:
            seen.append(value)

    norm = normalize_repo_path(git_path)
    if norm is None:
        return PolicyPathSet(paths=[], escaped=True)
    _add(norm)

    link = Path(repo) / norm
    try:
        is_link = link.is_symlink()
    except OSError:
        is_link = False
    if is_link or link.exists():
        real = realpath_in_repo(repo, git_path)
        if real is None:
            escaped = True
        else:
            _add(real)

    target = git_symlink_target(repo, commit, git_path)
    if target:
        resolved = resolve_symlink_target_path(git_path, target)
        if resolved is None:
            escaped = True
        else:
            _add(resolved)
    return PolicyPathSet(paths=seen, escaped=escaped)


def parse_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def command_argv(command: str | dict[str, Any]) -> tuple[str, ...] | None:
    argv = parse_command(command)
    if not argv:
        return None
    return tuple(argv)


def command_from_log_record(record: dict[str, Any]) -> str | dict[str, Any] | None:
    if "argv" in record and isinstance(record["argv"], list) and record["argv"]:
        argv = [str(a) for a in record["argv"]]
        return {"executable": argv[0], "args": argv[1:]}
    raw = record.get("command") or record.get("cmd")
    if isinstance(raw, dict):
        return raw
    if raw:
        return str(raw)
    return None


def load_adapter_log(path: Path | None) -> AdapterLog:
    if path is None:
        return AdapterLog(
            ok=False,
            issues=[
                (
                    "MISSING_ADAPTER_LOG",
                    "log estruturado do adapter ausente — comandos do payload não são evidência",
                )
            ],
        )
    log_path = Path(path)
    if not log_path.is_file():
        return AdapterLog(
            ok=False,
            issues=[
                (
                    "MISSING_ADAPTER_LOG",
                    f"log estruturado do adapter não encontrado: {log_path}",
                )
            ],
        )
    records: list[dict[str, Any]] = []
    issues: list[tuple[str, str]] = []
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        return AdapterLog(
            ok=False,
            issues=[("INVALID_ADAPTER_LOG", f"não foi possível ler {log_path}: {exc}")],
        )
    if not text.strip():
        return AdapterLog(
            ok=True,
            path=log_path,
            records=[],
            commands=[],
            sha256=sha256_of(log_path),
        )
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            issues.append(
                ("INVALID_ADAPTER_LOG", f"linha {i + 1} do adapter log não é JSON")
            )
            continue
        if not isinstance(rec, dict):
            issues.append(
                ("INVALID_ADAPTER_LOG", f"linha {i + 1} do adapter log não é objeto")
            )
            continue
        if parse_timestamp(rec.get("timestamp") or rec.get("ts")) is None:
            issues.append(
                (
                    "INVALID_ADAPTER_LOG",
                    f"linha {i + 1} sem timestamp ISO-8601",
                )
            )
            continue
        cmd = command_from_log_record(rec)
        if cmd is None or command_argv(cmd) is None:
            issues.append(
                (
                    "INVALID_ADAPTER_LOG",
                    f"linha {i + 1} sem comando estruturado (argv/command)",
                )
            )
            continue
        exit_code = rec.get("exit_code")
        if not isinstance(exit_code, int):
            issues.append(
                (
                    "INVALID_ADAPTER_LOG",
                    f"linha {i + 1} sem exit_code inteiro",
                )
            )
            continue
        records.append(rec)
    commands: list[str | dict[str, Any]] = []
    for rec in records:
        cmd = command_from_log_record(rec)
        if cmd is not None:
            commands.append(cmd)
    ok = not issues
    return AdapterLog(
        ok=ok,
        issues=issues,
        path=log_path,
        records=records,
        commands=commands,
        sha256=sha256_of(log_path),
    )


def canonical_command_set(commands: list[Any]) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for cmd in commands:
        argv = command_argv(cmd)
        if argv:
            out.add(argv)
    return out


def parse_trace_locator(item: Any) -> tuple[str | None, int | None, int | None]:
    if isinstance(item, dict):
        path = item.get("path") or item.get("file")
        start = item.get("line") if item.get("line") is not None else item.get("start_line")
        end = item.get("end_line") if item.get("end_line") is not None else start
        try:
            start_i = int(start) if start is not None else None
        except (TypeError, ValueError):
            start_i = None
        try:
            end_i = int(end) if end is not None else None
        except (TypeError, ValueError):
            end_i = None
        return (str(path) if path else None, start_i, end_i)
    text = str(item or "").strip()
    if not text:
        return None, None, None
    if ":" in text:
        path, _, rest = text.rpartition(":")
        if rest.isdigit():
            line = int(rest)
            return path, line, line
        if "-" in rest:
            a, b = rest.split("-", 1)
            if a.isdigit() and b.isdigit():
                return path, int(a), int(b)
    return text, None, None


def trace_in_result_commit(
    repo: Path, commit: str, locator: Any
) -> tuple[bool, str | None]:
    path, start, end = parse_trace_locator(locator)
    if not path:
        return False, "locator de rastreio sem path"
    norm = normalize_repo_path(path)
    if norm is None:
        return False, f"path de rastreio inválido: {path}"
    if not git_file_exists(repo, commit, norm):
        return False, f"{norm} não existe em {commit[:12]}"
    if start is None and end is None:
        return True, None
    lines = git_file_line_count(repo, commit, norm)
    if lines is None:
        return False, f"não foi possível ler {norm} em {commit[:12]}"
    for line in (start, end):
        if line is None:
            continue
        if line < 1 or line > lines:
            return False, f"{norm}:{line} fora do arquivo ({lines} linhas) em {commit[:12]}"
    return True, None


def resolve_artifact_path(
    raw: str,
    *,
    roots: list[Path],
) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    candidate = Path(value)
    search: list[Path] = [candidate] if candidate.is_absolute() else [root / candidate for root in roots]
    resolved_roots = [Path(root).resolve() for root in roots]
    for path in search:
        try:
            if not path.exists():
                continue
            resolved = path.resolve()
            if not resolved.is_file():
                continue
            for root in resolved_roots:
                try:
                    return resolve_within(root, resolved)
                except UnsafePath:
                    continue
        except OSError:
            continue
    return None


def test_evidence_errors(
    test: dict[str, Any],
    *,
    adapter: AdapterLog,
    artifact_roots: list[Path],
) -> list[tuple[str, str]]:
    """Recusa teste apenas declarado, sem execução verificável."""
    issues: list[tuple[str, str]] = []
    name = str(test.get("name") or test)
    command = test.get("command") or test.get("cmd")
    if command is None and isinstance(test.get("argv"), list):
        argv = [str(a) for a in test["argv"]]
        command = {"executable": argv[0], "args": argv[1:]} if argv else None
    argv = command_argv(command) if command is not None else None
    if argv is None:
        issues.append(
            (
                "TEST_NOT_EVIDENCED",
                f"teste `{name}` sem comando verificável",
            )
        )
    exit_code = test.get("exit_code")
    if not isinstance(exit_code, int):
        issues.append(
            (
                "TEST_NOT_EVIDENCED",
                f"teste `{name}` sem exit_code inteiro",
            )
        )
    if parse_timestamp(test.get("timestamp") or test.get("ts")) is None:
        issues.append(
            (
                "TEST_NOT_EVIDENCED",
                f"teste `{name}` sem timestamp ISO-8601",
            )
        )
    artifact_raw = test.get("log") or test.get("artifact") or test.get("log_path")
    artifact = (
        resolve_artifact_path(str(artifact_raw), roots=artifact_roots)
        if artifact_raw
        else None
    )
    if artifact is None:
        issues.append(
            (
                "TEST_NOT_EVIDENCED",
                f"teste `{name}` sem artefato/log verificável",
            )
        )
    else:
        test["_artifact_path"] = str(artifact)
        test["_artifact_sha256"] = sha256_of(artifact)

    if argv is not None and isinstance(exit_code, int) and adapter.ok:
        matched = False
        for rec in adapter.records:
            rec_cmd = command_from_log_record(rec)
            rec_argv = command_argv(rec_cmd) if rec_cmd is not None else None
            if rec_argv == argv and rec.get("exit_code") == exit_code:
                matched = True
                break
        if not matched:
            issues.append(
                (
                    "TEST_NOT_EVIDENCED",
                    f"teste `{name}` não aparece no log estruturado do adapter",
                )
            )

    passed = bool(test.get("passed", True))
    if isinstance(exit_code, int):
        if passed and exit_code != 0:
            issues.append(
                (
                    "EVIDENCE_DIVERGENCE",
                    f"teste `{name}` relatou passed=true com exit_code={exit_code}",
                )
            )
        if not passed and exit_code == 0:
            issues.append(
                (
                    "EVIDENCE_DIVERGENCE",
                    f"teste `{name}` relatou passed=false com exit_code=0",
                )
            )
    return issues


def build_evidence_hashes(
    *,
    git: GitInspection | None,
    adapter: AdapterLog | None,
    tests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Hashes reproduzíveis a partir do repo e dos logs; HMAC reusa o selo do 19."""
    payload: dict[str, Any] = {
        "base_commit": git.base_sha if git else None,
        "result_commit": git.result_sha if git else None,
        "changed_files_sha256": (
            canonical_json_hash(list(git.changed_files)) if git and git.ok else None
        ),
        "diff_sha256": hash_bytes((git.diff_raw or "").encode("utf-8")) if git and git.ok else None,
        "adapter_log_sha256": adapter.sha256 if adapter else None,
        "test_artifacts": [
            {
                "name": str(t.get("name") or ""),
                "sha256": t.get("_artifact_sha256"),
            }
            for t in tests
            if t.get("_artifact_sha256")
        ],
        "kid": current_kid(),
    }
    try:
        payload["hmac"] = seal_hmac(
            {k: v for k, v in payload.items() if k not in _UNSIGNED_HASH_FIELDS}
        )
    except MissingIntegrityKey:
        payload["hmac"] = None
    return payload
