"""Runtime de execução isolada por run_id."""
from __future__ import annotations

from src.runtime.atomic_io import UnsafePath
from src.runtime.checkpoint import CHECKPOINT_SCHEMA_VERSION, CheckpointStore
from src.runtime.graph import GraphError, StageSpec, load_stage_graph
from src.runtime.handlers import default_registry
from src.runtime.orchestrator import Orchestrator, build_run_result
from src.runtime.run_context import (
    CHECKPOINTS_DIRNAME,
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
from src.runtime.event_store import EventStore
from src.runtime.run_store import (
    InvalidStatusTransition,
    RunIdCollision,
    RunStateConflict,
    RunStore,
)
from src.runtime.stage import (
    HandlerRegistry,
    HashMismatch,
    Stage,
    StageContext,
    StageError,
    StageResult,
    StageTimeout,
)

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "CHECKPOINTS_DIRNAME",
    "CONTEXTS_DIRNAME",
    "CheckpointStore",
    "EventStore",
    "GraphError",
    "HandlerRegistry",
    "HashMismatch",
    "InvalidContextId",
    "InvalidRunId",
    "InvalidStatusTransition",
    "Orchestrator",
    "RunContext",
    "RunIdCollision",
    "RunStateConflict",
    "RunStore",
    "Stage",
    "StageContext",
    "StageError",
    "StageResult",
    "StageSpec",
    "StageTimeout",
    "UnsafePath",
    "UnsafeRunPath",
    "build_run_result",
    "context_subdir",
    "default_registry",
    "load_stage_graph",
    "new_run_id",
    "validate_context_id",
    "validate_run_id",
]
