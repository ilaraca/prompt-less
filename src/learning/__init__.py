"""Pacote de aprendizado / autoaperfeiçoamento controlado."""
from __future__ import annotations

from src.learning.accept import decide_proposals, load_history
from src.learning.apply_rollback import apply_proposals_with_rollback
from src.learning.evals import (
    RESERVED_CASES,
    apply_reserved_gate,
    build_experiment_record,
    compare_evals,
    partition_cases,
    run_eval_suite,
)
from src.learning.failure_patterns import classify_issues, diagnose_verify_report
from src.learning.proposals import build_proposals
from src.learning.workspaces import (
    ProtectedSurfaceError,
    apply_proposals_to_candidate,
    is_protected_change,
    materialize_eval_workspaces,
)

__all__ = [
    "RESERVED_CASES",
    "ProtectedSurfaceError",
    "apply_proposals_to_candidate",
    "apply_proposals_with_rollback",
    "apply_reserved_gate",
    "build_experiment_record",
    "build_proposals",
    "classify_issues",
    "compare_evals",
    "decide_proposals",
    "diagnose_verify_report",
    "is_protected_change",
    "load_history",
    "materialize_eval_workspaces",
    "partition_cases",
    "run_eval_suite",
]
