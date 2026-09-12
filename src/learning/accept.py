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
        return {"accepted": [], "rejected": []}
    return json.loads(path.read_text(encoding="utf-8"))


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
    history = load_history(root)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    if comparison.get("decision") == "reject" or comparison.get("regression"):
        for p in proposals:
            item = {**p, "status": "rejected", "decided_at": now, "reason": comparison.get("reasons")}
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
                item = {**p, "status": "accepted", "decided_at": now}
                accepted.append(item)
                history["accepted"].append(item)

    path = save_history(root, history)
    return {
        "accepted": accepted,
        "rejected": rejected,
        "history_path": str(path),
        "comparison": comparison,
    }
