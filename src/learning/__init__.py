"""Pacote de aprendizado / autoaperfeiçoamento controlado."""
from __future__ import annotations

from src.learning.accept import decide_proposals, load_history
from src.learning.evals import compare_evals, run_eval_suite
from src.learning.failure_patterns import classify_issues, diagnose_verify_report
from src.learning.proposals import build_proposals
from src.learning.workspaces import (
    apply_proposals_to_candidate,
    materialize_eval_workspaces,
)

__all__ = [
    "apply_proposals_to_candidate",
    "build_proposals",
    "classify_issues",
    "compare_evals",
    "decide_proposals",
    "diagnose_verify_report",
    "load_history",
    "materialize_eval_workspaces",
    "run_eval_suite",
]
