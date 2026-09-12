"""Gera propostas limitadas a partir de playbooks."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAYBOOK = ROOT / "config" / "playbook.yaml"


def load_playbooks(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or DEFAULT_PLAYBOOK).read_text(encoding="utf-8")) or {}
    return dict(data.get("playbooks") or {})


def build_proposals(
    diagnosis: dict[str, Any],
    *,
    playbooks: dict[str, Any] | None = None,
    max_proposals: int = 3,
) -> list[dict[str, Any]]:
    playbooks = playbooks or load_playbooks()
    names = list((diagnosis.get("recommended_action") or {}).get("playbooks") or [])
    proposals: list[dict[str, Any]] = []
    for name in names[:max_proposals]:
        pb = playbooks.get(name)
        if not pb:
            continue
        proposals.append(
            {
                "id": f"PROP-{uuid4().hex[:8]}",
                "playbook": name,
                "proposal_type": pb.get("proposal_type"),
                "description": pb.get("description"),
                "change": pb.get("change"),
                "risk": pb.get("risk") or "low",
                "status": "proposed",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    return proposals
