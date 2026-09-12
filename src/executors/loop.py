"""Pedido de reparo limitado a partir de VerifyResult."""
from __future__ import annotations

from typing import Any

from src.executors.base import ExecutionResult
from src.executors.verify import VerifyResult

MAX_REPAIR_ATTEMPTS = 2


def build_repair_request(
    verify: VerifyResult,
    execution: ExecutionResult,
    *,
    attempt: int = 1,
    max_attempts: int = MAX_REPAIR_ATTEMPTS,
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

    editable = sorted(
        {
            i.subject_id
            for i in errors
            if i.subject_id and i.code in {"FILE_OUT_OF_SCOPE", "RF_NOT_MAPPED", "TEST_FAILED"}
        }
    )
    return {
        "status": "repair_requested",
        "attempt": attempt,
        "max_attempts": max_attempts,
        "run_id": execution.run_id,
        "repository": execution.repository,
        "requires_approval": True,
        "editable_surface": editable,
        "protected": [".github/workflows/**", "infra/prod/**", "**/*.pem"],
        "failures": [i.to_dict() for i in errors],
        "instructions": (
            "Corrija apenas as falhas listadas. Não altere superfície protegida. "
            "Reenvie ExecutionResult estruturado após o reparo."
        ),
    }
