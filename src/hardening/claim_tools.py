"""Tools de recovery sob demanda: search_claims / get_claim sobre claims da run."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TOOL_SEARCH_CLAIMS = "search_claims"
TOOL_GET_CLAIM = "get_claim"

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def claim_tool_specs() -> list[dict[str, Any]]:
    """Contrato neutro das tools (o pacote LLM adapta para OpenAI/Claude)."""
    return [
        {
            "name": TOOL_SEARCH_CLAIMS,
            "description": (
                "Busca claims persistidos da run por texto. "
                "Filtra por service_id quando informado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "texto ou tokens a localizar"},
                    "service_id": {
                        "type": "string",
                        "description": "restringe ao serviço, se o claim tiver service_id",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": TOOL_GET_CLAIM,
            "description": "Recupera um claim pelo id exato (não inventa se faltar).",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                },
                "required": ["claim_id"],
            },
        },
    ]


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in claim_tool_specs()
    ]


def claude_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for spec in claim_tool_specs()
    ]


def _as_claim(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cid = str(raw.get("id") or "").strip()
    if not cid:
        return None
    return raw


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t}


def search_claims(
    claims: list[dict[str, Any]] | None,
    query: str,
    *,
    service_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retorna claims da run cujo texto/id sobrepõe a query. Vazio se nada casar."""
    needle = (query or "").strip()
    if not needle:
        return []
    q_tokens = _tokens(needle)
    q_lower = needle.lower()
    hits: list[tuple[int, dict[str, Any]]] = []
    for raw in claims or []:
        claim = _as_claim(raw)
        if claim is None:
            continue
        if service_id:
            sid = claim.get("service_id")
            if sid and str(sid) != str(service_id):
                continue
        blob = " ".join(
            str(claim.get(k) or "") for k in ("id", "text", "chunk_id", "service_id")
        ).lower()
        if q_lower in blob:
            score = 100 + blob.count(q_lower)
        else:
            overlap = len(q_tokens & _tokens(blob))
            if overlap == 0:
                continue
            score = overlap
        hits.append((score, claim))
    hits.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    return [c for _, c in hits[: max(1, limit)]]


def get_claim(
    claims: list[dict[str, Any]] | None,
    claim_id: str,
) -> dict[str, Any] | None:
    wanted = str(claim_id or "").strip()
    if not wanted:
        return None
    for raw in claims or []:
        claim = _as_claim(raw)
        if claim is not None and str(claim.get("id")) == wanted:
            return claim
    return None


def load_run_claims(run_dir: Path) -> list[dict[str, Any]]:
    """Lê claims de `validations/provenance.json` da run. Lista vazia se ausente."""
    path = Path(run_dir) / "validations" / "provenance.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[dict[str, Any]] = []
    for raw in data.get("claims") or []:
        claim = _as_claim(raw)
        if claim is not None:
            out.append(claim)
    return out


def dispatch_tool(
    name: str,
    arguments: dict[str, Any] | str | None,
    claims: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Executa a tool pelo nome. Tool desconhecida ou args inválidos falham fechado."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return {"ok": False, "error": "arguments_invalid_json"}
    args = arguments if isinstance(arguments, dict) else {}
    if name == TOOL_SEARCH_CLAIMS:
        query = str(args.get("query") or "")
        service_id = args.get("service_id")
        hits = search_claims(
            claims, query, service_id=str(service_id) if service_id else None
        )
        return {"ok": True, "tool": name, "count": len(hits), "claims": hits}
    if name == TOOL_GET_CLAIM:
        found = get_claim(claims, str(args.get("claim_id") or ""))
        if found is None:
            return {"ok": False, "tool": name, "error": "claim_not_found"}
        return {"ok": True, "tool": name, "claim": found}
    return {"ok": False, "error": "unknown_tool", "tool": name}
