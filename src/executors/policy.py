"""Policies de permissão por camada (auditoria estruturada de argv)."""
from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = ROOT / "config" / "permission_profiles.yaml"
KNOWN_LAYERS = ("bff", "api", "mfe", "gtw", "worker", "batch")

# Metacaracteres de shell — presença = comando composto / injection
_SHELL_META = re.compile(r"[;&|`$()<>\n]|\s&&\s|\s\|\|\s")
_FLAG_RE = re.compile(r"^--?[A-Za-z0-9][\w.-]*(=.*)?$")
_EXT_RE = re.compile(
    r"\.(?:java|py|ts|tsx|js|jsx|kt|go|yaml|yml|json|xml|md|txt|properties|gradle)$",
    re.IGNORECASE,
)


def load_profiles(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PROFILES
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("profiles") or {}


def normalize_repo_path(raw: str) -> str | None:
    """
    Aceita apenas paths relativos canônicos dentro do repo.

    Rejeita absolutos, drive letters, segmentos vazios/`.`/`..` e traversal.
    """
    if raw is None:
        return None
    value = str(raw).strip().replace("\\", "/")
    if not value:
        return None
    if value.startswith("/") or value.startswith("//"):
        return None

    path = PurePosixPath(value)
    if path.is_absolute():
        return None

    parts = path.parts
    if not parts:
        return None
    if parts[0].endswith(":"):
        return None
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if ".." in value.split("/"):
        return None

    return path.as_posix()


def _stays_in_root(root: Path, candidate: Path) -> bool:
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def resolve_repo_path(raw: str, repo_root: Path | str | None = None) -> str | None:
    """
    Normaliza e, com `repo_root`, resolve realpath/symlinks.

    Qualquer componente existente cujo resolve() saia do repositório é recusado.
    """
    normalized = normalize_repo_path(raw)
    if normalized is None:
        return None
    if repo_root is None:
        return normalized

    try:
        root = Path(repo_root).resolve()
    except OSError:
        return None

    current = root
    for part in PurePosixPath(normalized).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if not _stays_in_root(root, current):
                return None

    parent = (root / normalized).parent
    if parent.exists() or parent.is_symlink():
        if not _stays_in_root(root, parent):
            return None
    return normalized


def _match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def check_write_allowed(
    path: str,
    profile: dict[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> bool:
    normalized = resolve_repo_path(path, repo_root)
    if normalized is None:
        return False

    deny = list(profile.get("write_deny") or [])
    allow = list(profile.get("write_allow") or [])
    if _match_any(normalized, deny):
        return False
    if not allow:
        return True
    return _match_any(normalized, allow)


def parse_command(command: str | dict[str, Any] | list[str]) -> list[str] | None:
    """Normaliza comando para argv. Retorna None se inválido / shell composto."""
    if isinstance(command, list):
        if not command:
            return None
        argv = [str(a) for a in command]
        if any(_SHELL_META.search(a) for a in argv):
            return None
        return argv
    if isinstance(command, dict):
        exe = command.get("executable") or command.get("cmd")
        if not exe:
            return None
        args = command.get("args") or []
        if not isinstance(args, list):
            return None
        argv = [str(exe), *[str(a) for a in args]]
        if any(_SHELL_META.search(a) for a in argv):
            return None
        return argv

    cmd = (command or "").strip()
    if not cmd:
        return None
    if _SHELL_META.search(cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    return argv or None


def _rule_prefix(rule: str | dict[str, Any]) -> list[str] | None:
    """Prefixo semântico da regra: executable + args exigidos (tokens exatos)."""
    if isinstance(rule, dict):
        exe = rule.get("executable") or rule.get("cmd")
        if not exe:
            return None
        extra = rule.get("args") if rule.get("args") is not None else rule.get("subcommands")
        if extra is None:
            extra = []
        if not isinstance(extra, list):
            return None
        prefix = [str(exe), *[str(a) for a in extra]]
        if any(_SHELL_META.search(a) for a in prefix):
            return None
        return prefix
    if not isinstance(rule, str):
        return None
    try:
        parsed = shlex.split(rule.strip())
    except ValueError:
        return None
    return parsed or None


def _argv_matches_prefix(argv: list[str], prefix: list[str]) -> bool:
    if not prefix or len(argv) < len(prefix):
        return False
    return argv[: len(prefix)] == prefix


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if value.startswith(("/", "~")) or (len(value) >= 2 and value[1] == ":"):
        return True
    if ".." in value.split("/") or "\\" in value:
        return True
    if "/" in value:
        return True
    return bool(_EXT_RE.search(value))


def _flag_value(arg: str) -> str | None:
    if arg.startswith("-") and "=" in arg:
        return arg.split("=", 1)[1]
    return None


def extra_args_allowed(argv: list[str], prefix_len: int, *, repo_root: Path | str | None = None) -> bool:
    """Valida argumentos além do prefixo da allowlist (paths relativos, flags)."""
    for arg in argv[prefix_len:]:
        if not arg or _SHELL_META.search(arg):
            return False
        value = _flag_value(arg)
        candidate = value if value is not None else arg
        if value is None and _FLAG_RE.match(arg) and "=" not in arg:
            continue
        if _looks_like_path(candidate):
            if resolve_repo_path(candidate, repo_root) is None:
                return False
            continue
        if value is not None:
            continue
        if _FLAG_RE.match(arg):
            continue
        # posicional que não parece path: só aceita se for relativo canônico
        if resolve_repo_path(arg, repo_root) is None:
            return False
    return True


def check_command_allowed(
    command: str | dict[str, Any] | list[str],
    profile: dict[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> bool:
    """
    Valida comando como argv (sem shell).

    Allow/deny comparam tokens, não prefixo de string. Argumentos extras são
    checados semanticamente: path tem de sobreviver a `realpath`/normalize.
    """
    argv = parse_command(command)
    if argv is None:
        return False
    if any(_SHELL_META.search(a) for a in argv):
        return False

    for denied in profile.get("commands_deny") or []:
        prefix = _rule_prefix(denied)
        if prefix and _argv_matches_prefix(argv, prefix):
            return False

    allow = list(profile.get("commands_allow") or [])
    if not allow:
        return extra_args_allowed(argv, 1, repo_root=repo_root)

    for rule in allow:
        prefix = _rule_prefix(rule)
        if not prefix:
            continue
        if not _argv_matches_prefix(argv, prefix):
            continue
        if extra_args_allowed(argv, len(prefix), repo_root=repo_root):
            return True
    return False
