"""Aceite/rejeição de propostas com histórico persistente."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime.atomic_io import atomic_write_json, read_json

PROVEN_STATUSES = frozenset({"accepted", "approved_for_experiment"})
HISTORY_KEYS = (
    "proposed",
    "applied_to_candidate",
    "evaluated",
    "approved_for_experiment",
    "accepted",
    "rejected",
)


def knowledge_dir(root: Path) -> Path:
    d = root / "state" / "knowledge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_history(root: Path) -> dict[str, Any]:
    path = knowledge_dir(root) / "proposals-history.json"
    data = read_json(path)
    if not isinstance(data, dict):
        data = {}
    for key in HISTORY_KEYS:
        data.setdefault(key, [])
    return data


def save_history(root: Path, history: dict[str, Any]) -> Path:
    path = knowledge_dir(root) / "proposals-history.json"
    for key in HISTORY_KEYS:
        history.setdefault(key, [])
    atomic_write_json(path, history)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _applied_ids(apply_result: dict[str, Any] | None) -> set[str]:
    if not apply_result:
        return set()
    if apply_result.get("status") != "applied":
        return set()
    return {str(i) for i in (apply_result.get("applied_ids") or []) if i}


def decide_proposals(
    proposals: list[dict[str, Any]],
    comparison: dict[str, Any],
    *,
    root: Path,
    apply_result: dict[str, Any] | None = None,
    experiment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Gate de propostas no candidato.

    `accepted` = melhoria comprovada no workspace candidato (não é apply em
    produção). Sem apply no candidato, a proposta nunca entra em
    `accepted` nem `approved_for_experiment`.

    Conjuntos incomparáveis, regressão por caso (sem tolerância explícita),
    regressão/falha crítica no hold-out (`reserved_case_gates`) ou ausência
    de benefício demonstrável (latência não conta) bloqueiam promoção.
    """
    history = load_history(root)
    now = _now()
    applied_ids = _applied_ids(apply_result)
    diff = ""
    if apply_result:
        diff = str(apply_result.get("diff") or "")
    metrics = comparison.get("metrics") or {}
    workspaces = comparison.get("workspaces") or {}
    experiment_record = experiment or comparison.get("experiment")

    proposed: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    reject_cmp = (
        comparison.get("decision") == "reject"
        or comparison.get("regression")
        or comparison.get("critical_regression")
        or comparison.get("comparable") is False
    )
    distinct = bool((workspaces.get("distinct") if workspaces else True) is not False)
    if workspaces and workspaces.get("baseline") and workspaces.get("candidate"):
        distinct = bool(workspaces.get("distinct"))

    def _record(bucket: str, item: dict[str, Any]) -> None:
        history[bucket].append(item)

    for raw in proposals:
        pid = str(raw.get("id") or "")
        base = {
            **raw,
            "decided_at": now,
            "diff": diff,
            "metrics": metrics,
            "workspaces": workspaces,
            "case_gates": comparison.get("case_gates") or [],
            "reserved_case_gates": comparison.get("reserved_case_gates") or [],
            "tolerances_applied": comparison.get("tolerances_applied") or [],
            "comparable": comparison.get("comparable", True),
        }
        if experiment_record:
            base["experiment"] = experiment_record
        proposed_item = {**base, "status": "proposed"}
        proposed.append(proposed_item)
        _record("proposed", proposed_item)

        was_applied = pid in applied_ids
        if was_applied:
            applied_item = {**base, "status": "applied_to_candidate"}
            applied.append(applied_item)
            _record("applied_to_candidate", applied_item)
            eval_item = {**base, "status": "evaluated"}
            evaluated.append(eval_item)
            _record("evaluated", eval_item)

        reasons: list[str] = []
        terminal = "rejected"
        if not was_applied:
            reasons = ["proposal_not_applied"]
        elif not distinct:
            reasons = ["workspaces_not_distinct"]
        elif comparison.get("comparable") is False:
            reasons = list(comparison.get("reasons") or ["incomparable_case_sets"])
        elif reject_cmp:
            reasons = list(comparison.get("reasons") or ["eval_regression"])
        elif (raw.get("risk") or "low") not in {"low"}:
            reasons = ["human_approval_required_for_risk"]
        elif comparison.get("improved"):
            terminal = "accepted"
        else:
            # sem benefício demonstrável (ex.: só jitter de latência)
            terminal = "approved_for_experiment"

        item = {**base, "status": terminal, "reason": reasons}
        if terminal in PROVEN_STATUSES and not was_applied:
            item["status"] = "rejected"
            item["reason"] = ["proposal_not_applied"]
            terminal = "rejected"

        if terminal == "accepted":
            accepted.append(item)
            _record("accepted", item)
        elif terminal == "approved_for_experiment":
            approved.append(item)
            _record("approved_for_experiment", item)
        else:
            rejected.append(item)
            _record("rejected", item)

    path = save_history(root, history)
    return {
        "proposed": proposed,
        "applied_to_candidate": applied,
        "evaluated": evaluated,
        "approved_for_experiment": approved,
        "accepted": accepted,
        "rejected": rejected,
        "history_path": str(path),
        "comparison": comparison,
        "experiment": experiment_record,
    }
