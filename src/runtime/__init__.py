"""Runtime de execução isolada por run_id."""
from __future__ import annotations

from src.runtime.atomic_io import UnsafePath
from src.runtime.run_context import (
    CONTEXTS_DIRNAME,
    InvalidContextId,
    InvalidRunId,
    RunContext,
    UnsafeRunPath,
    context_subdir,
    new_run_id,
    validate_context_id,
    validate_run_id,
)
from src.runtime.approval import (
    ApprovalError,
    ApprovalExpired,
    ApprovalMissing,
    ApprovalRejected,
    ApprovalReuse,
    ApprovalTampered,
)
from src.runtime.event_store import EventStore
from src.runtime.integrity import MissingIntegrityKey, verify_run_dir
from src.runtime.run_store import (
    InvalidStatusTransition,
    RunIdCollision,
    RunStateConflict,
    RunStore,
)

__all__ = [
    "ApprovalError",
    "ApprovalExpired",
    "ApprovalMissing",
    "ApprovalRejected",
    "ApprovalReuse",
    "ApprovalTampered",
    "CONTEXTS_DIRNAME",
    "EventStore",
    "InvalidContextId",
    "InvalidRunId",
    "InvalidStatusTransition",
    "RunContext",
    "RunIdCollision",
    "RunStateConflict",
    "RunStore",
    "UnsafePath",
    "UnsafeRunPath",
    "context_subdir",
    "new_run_id",
    "validate_context_id",
    "validate_run_id",
    "MissingIntegrityKey",
    "verify_run_dir",
]
