"""Aceite/rejeição de propostas com histórico persistente."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def knowledge_dir(root: Path) -> Path:
    d = root / "state" / "knowledge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_history(root: Path) -> dict[str, Any]:
    path = knowledge_dir(root) / "proposals-history.json"
    if not path.exists():
        return {"accepted": [], "rejected": [], "approved_for_experiment": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("accepted", [])  # legado
    data.setdefault("rejected", [])
    data.setdefault("approved_for_experiment", [])
    return data


def save_history(root: Path, history: dict[str, Any]) -> Path:
    path = knowledge_dir(root) / "proposals-history.json"
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def decide_proposals(
    proposals: list[dict[str, Any]],
    comparison: dict[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    """
    Gate de propostas.

    Enquanto não houver workspace candidato separado, o estado positivo é
    `approved_for_experiment` (não `accepted`) — a proposta entra no knowledge
    store para experimento, sem afirmar melhoria comprovada.
    """
    history = load_history(root)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    if comparison.get("decision") == "reject" or comparison.get("regression"):
        for p in proposals:
            item = {
                **p,
                "status": "rejected",
                "decided_at": now,
                "reason": comparison.get("reasons"),
            }
            rejected.append(item)
            history["rejected"].append(item)
    else:
        for p in proposals:
            # risco medium+ exige aprovação humana mesmo sem regressão de eval
            if (p.get("risk") or "low") not in {"low"}:
                item = {
                    **p,
                    "status": "rejected",
                    "decided_at": now,
                    "reason": ["human_approval_required_for_risk"],
                }
                rejected.append(item)
                history["rejected"].append(item)
            else:
                item = {
                    **p,
                    "status": "approved_for_experiment",
                    "decided_at": now,
                }
                approved.append(item)
                history["approved_for_experiment"].append(item)

    path = save_history(root, history)
    return {
        # chave legada para callers; semanticamente = approved_for_experiment
        "accepted": approved,
        "approved_for_experiment": approved,
        "rejected": rejected,
        "history_path": str(path),
        "comparison": comparison,
    }
