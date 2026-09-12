"""Pedido de reparo limitado a partir de VerifyResult."""
from __future__ import annotations

import fnmatch
from typing import Any

from src.executors.base import ExecutionResult
from src.executors.verify import VerifyResult

MAX_REPAIR_ATTEMPTS = 2

DEFAULT_PROTECTED = [".github/workflows/**", "infra/prod/**", "**/*.pem"]


def _is_protected(path: str, patterns: list[str]) -> bool:
    norm = path.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pat) for pat in patterns)


def _looks_like_path(value: str) -> bool:
    return "/" in value or value.endswith(
        (".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".kt", ".go", ".yaml", ".yml", ".json")
    )


def build_repair_request(
    verify: VerifyResult,
    execution: ExecutionResult,
    *,
    attempt: int = 1,
    max_attempts: int = MAX_REPAIR_ATTEMPTS,
    protected: list[str] | None = None,
) -> dict[str, Any] | None:
    if attempt > max_attempts:
        return {
            "status": "exhausted",
            "attempt": attempt,
            "max_attempts": max_attempts,
            "message": "Limite de reparos atingido — intervenção humana obrigatória",
            "issues": [i.to_dict() for i in verify.issues if i.severity == "error"],
        }

    errors = [i for i in verify.issues if i.severity == "error"]
    if not errors:
        return None

    protected_patterns = list(protected or DEFAULT_PROTECTED)

    # FILE_OUT_OF_SCOPE → reverter, nunca liberar como superfície editável
    required_reverts = sorted(
        {
            i.subject_id
            for i in errors
            if i.code == "FILE_OUT_OF_SCOPE" and i.subject_id
        }
    )

    # editable: arquivos in-scope já alterados + paths de TEST_FAILED (não RF_*)
    revert_set = set(required_reverts)
    editable: set[str] = set()
    for path in execution.changed_files:
        if path in revert_set:
            continue
        if _is_protected(path, protected_patterns):
            continue
        editable.add(path)

    for i in errors:
        if i.code == "TEST_FAILED" and i.subject_id and _looks_like_path(i.subject_id):
            if i.subject_id not in revert_set and not _is_protected(
                i.subject_id, protected_patterns
            ):
                editable.add(i.subject_id)
        # RF_NOT_MAPPED / AC_NOT_MAPPED usam IDs (RF-001), não caminhos — ignorar

    return {
        "status": "repair_requested",
        "attempt": attempt,
        "max_attempts": max_attempts,
        "run_id": execution.run_id,
        "repository": execution.repository,
        "requires_approval": True,
        "required_reverts": required_reverts,
        "editable_surface": sorted(editable),
        "protected": protected_patterns,
        "failures": [i.to_dict() for i in errors],
        "instructions": (
            "Reverta arquivos em required_reverts. Corrija apenas editable_surface. "
            "Não altere superfície protegida. "
            "Reenvie ExecutionResult estruturado após o reparo."
        ),
    }
