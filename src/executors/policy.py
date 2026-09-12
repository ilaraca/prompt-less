"""Policies de permissão por camada (auditoria estruturada de argv)."""
from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = ROOT / "config" / "permission_profiles.yaml"

# Metacaracteres de shell — presença = comando composto / injection
_SHELL_META = re.compile(r"[;&|`$()<>\n]|\s&&\s|\s\|\|\s")


def load_profiles(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PROFILES
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("profiles") or {}


def _match_any(path: str, patterns: list[str]) -> bool:
    norm = path.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pat) for pat in patterns)


def check_write_allowed(path: str, profile: dict[str, Any]) -> bool:
    deny = list(profile.get("write_deny") or [])
    allow = list(profile.get("write_allow") or [])
    if _match_any(path, deny):
        return False
    if not allow:
        return True
    return _match_any(path, allow)


def parse_command(command: str | dict[str, Any]) -> list[str] | None:
    """Normaliza comando para argv. Retorna None se inválido / shell composto."""
    if isinstance(command, dict):
        exe = command.get("executable") or command.get("cmd")
        if not exe:
            return None
        args = command.get("args") or []
        if not isinstance(args, list):
            return None
        return [str(exe), *[str(a) for a in args]]

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


def _argv_matches_rule(argv: list[str], rule: str) -> bool:
    """True se argv == rule ou argv é prefixo exato do rule (por tokens)."""
    try:
        rule_argv = shlex.split(rule.strip())
    except ValueError:
        return False
    if not rule_argv:
        return False
    if len(argv) < len(rule_argv):
        return False
    return argv[: len(rule_argv)] == rule_argv


def check_command_allowed(command: str | dict[str, Any], profile: dict[str, Any]) -> bool:
    """
    Valida comando como argv (sem shell).

    Comandos com metacaracteres (&&, ;, ||, pipes, etc.) são sempre negados.
    Allow/deny comparam tokens, não prefixo de string — evita
    `./mvnw test && terraform apply` passar pela allowlist de `./mvnw test`.
    """
    argv = parse_command(command)
    if argv is None:
        return False

    for denied in profile.get("commands_deny") or []:
        if _argv_matches_rule(argv, denied):
            return False

    allow = list(profile.get("commands_allow") or [])
    if not allow:
        return True
    return any(_argv_matches_rule(argv, a) for a in allow)
