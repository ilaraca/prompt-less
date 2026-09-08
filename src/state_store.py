"""Estado externo — substitui histórico de conversa no prompt."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "state" / "workflow.json"


def read_state(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(data: dict[str, Any], path: Path = DEFAULT_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # só campos relevantes ao workflow (padrão do artigo)
    docs_meta = [
        {"name": d.get("name"), "lines": d.get("lines"), "est_tokens_raw": d.get("est_tokens_raw")}
        for d in (data.get("documents") or [])
    ]
    slim = {
        "tipo": data.get("tipo"),
        "fluxo": (data.get("regras") or {}).get("fluxo"),
        "inputs": [i.get("name") for i in (data.get("ui") or {}).get("inputs", [])],
        "actions": (data.get("ui") or {}).get("actions", []),
        "bloqueios": (data.get("regras") or {}).get("bloqueios", []),
        "documents": docs_meta,  # metadados só — sem texto bruto
        "previous_actions": data.get("previous_actions", []),
        "status": data.get("status", "ready"),
    }
    path.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    return slim
