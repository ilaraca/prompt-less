"""Policies de permissão por camada."""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = ROOT / "config" / "permission_profiles.yaml"


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


def check_command_allowed(command: str, profile: dict[str, Any]) -> bool:
    cmd = command.strip()
    for denied in profile.get("commands_deny") or []:
        if cmd == denied or cmd.startswith(denied):
            return False
    allow = list(profile.get("commands_allow") or [])
    if not allow:
        return True
    return any(cmd == a or cmd.startswith(a) for a in allow)
