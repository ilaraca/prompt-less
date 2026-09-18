"""Pedido de reparo limitado a partir de VerifyResult."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.executors.base import ExecutionResult
from src.executors.policy import (
    check_write_allowed,
    load_profiles,
    resolve_repo_path,
)
from src.executors.verify import VerifyResult

MAX_REPAIR_ATTEMPTS = 2

# IDs de RF/AC/NFR/claim — nunca tratar como caminhos editáveis
_REQUIREMENT_ID_RE = re.compile(r"^(RF|AC|NFR|CLM)[-_]?\d+", re.IGNORECASE)

_EXT_RE = re.compile(
    r"\.(?:java|py|ts|tsx|js|jsx|kt|go|yaml|yml|json|xml|md|txt|properties|gradle)$",
    re.IGNORECASE,
)


def _is_requirement_id(value: str) -> bool:
    return bool(_REQUIREMENT_ID_RE.match(value.strip()))


def _looks_like_path(value: str) -> bool:
    """Heurística para subject_id de diagnóstico (TEST_FAILED); IDs RF/AC não passam."""
    if not value or _is_requirement_id(value):
        return False
    text = value.strip().replace("\\", "/")
    if text.startswith(("/", "~")) or (len(text) >= 2 and text[1] == ":"):
        return True
    if ".." in text.split("/") or "/" in text:
        return True
    return bool(_EXT_RE.search(text))


def _authorize_editable_path(
    raw: str,
    profile: dict[str, Any] | None,
    *,
    repo_root: Path | str | None,
) -> tuple[str | None, str | None]:
    """
    Reaplica política completa: normalize + realpath/symlink + write allow/deny.

    Retorna (path_canônico, motivo_negação).
    """
    if profile is None:
        return None, "profile_ausente"
    if _is_requirement_id(raw):
        return None, "id_nao_e_caminho"
    normalized = resolve_repo_path(raw, repo_root)
    if normalized is None:
        return None, "path_invalido_ou_escape"
    if not check_write_allowed(raw, profile, repo_root=repo_root):
        return None, "write_negado_pelo_profile"
    return normalized, None


def _resolve_profile(
    *,
    profile: dict[str, Any] | None,
    profiles: dict[str, Any] | None,
    layer: str | None,
    execution: ExecutionResult,
) -> tuple[dict[str, Any] | None, str | None]:
    if profile is not None:
        return profile, layer or execution.layer
    layer_name = layer or execution.layer
    loaded = profiles if profiles is not None else load_profiles()
    if layer_name and layer_name in loaded:
        return loaded[layer_name], layer_name
    return None, layer_name


def build_repair_request(
    verify: VerifyResult,
    execution: ExecutionResult,
    *,
    attempt: int = 1,
    max_attempts: int = MAX_REPAIR_ATTEMPTS,
    profile: dict[str, Any] | None = None,
    profiles: dict[str, Any] | None = None,
    layer: str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """
    Monta pedido de reparo reaplicando a política da tarefa a cada tentativa.

    Todo caminho proposto (changed_files e subject_id de diagnóstico) passa por
    `resolve_repo_path` + `check_write_allowed` com a raiz autorizada. Escapes
    (absoluto, `..`, symlink fora do repo) e IDs RF/AC nunca entram em
    `editable_surface`. `FILE_OUT_OF_SCOPE` vira só `required_reverts`.
    """
    if attempt > max_attempts:
        return {
            "status": "exhausted",
            "attempt": attempt,
            "max_attempts": max_attempts,
            "unresolved": True,
            "message": (
                "Limite de reparos atingido — falha persistente; "
                "intervenção humana obrigatória"
            ),
            "issues": [i.to_dict() for i in verify.issues if i.severity == "error"],
        }

    errors = [i for i in verify.issues if i.severity == "error"]
    if not errors:
        return None

    resolved_profile, layer_name = _resolve_profile(
        profile=profile,
        profiles=profiles,
        layer=layer,
        execution=execution,
    )
    write_deny = list((resolved_profile or {}).get("write_deny") or [])

    # FILE_OUT_OF_SCOPE → reverter, nunca liberar como superfície editável
    required_reverts = sorted(
        {
            i.subject_id
            for i in errors
            if i.code == "FILE_OUT_OF_SCOPE" and i.subject_id
        }
    )
    revert_set = set(required_reverts)

    editable: set[str] = set()
    denied: list[dict[str, str]] = []

    def _consider(raw: str, *, source: str) -> None:
        if raw in revert_set:
            return
        if raw in editable:
            return
        authorized, reason = _authorize_editable_path(
            raw, resolved_profile, repo_root=repo_root
        )
        if authorized is None:
            denied.append(
                {"path": raw, "source": source, "reason": reason or "negado"}
            )
            return
        editable.add(authorized)

    for path in execution.changed_files:
        _consider(path, source="changed_files")

    # Caminhos de diagnóstico (ex.: TEST_FAILED) só se a política autorizar
    for issue in errors:
        if issue.code != "TEST_FAILED" or not issue.subject_id:
            continue
        subject = issue.subject_id
        if _is_requirement_id(subject) or not _looks_like_path(subject):
            continue
        _consider(subject, source="diagnostic:TEST_FAILED")

    return {
        "status": "repair_requested",
        "attempt": attempt,
        "max_attempts": max_attempts,
        "run_id": execution.run_id,
        "repository": execution.repository,
        "layer": layer_name,
        "requires_approval": True,
        "required_reverts": required_reverts,
        "editable_surface": sorted(editable),
        "denied_paths": denied,
        "protected": write_deny,
        "failures": [i.to_dict() for i in errors],
        "instructions": (
            "Reverta arquivos em required_reverts. Corrija apenas editable_surface. "
            "Não altere superfície protegida nem caminhos em denied_paths. "
            "Após o reparo, reenvie ExecutionResult; o harness reexecuta verify "
            "completo antes de qualquer nova tentativa."
        ),
    }
