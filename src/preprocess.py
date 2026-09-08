"""Pré-processamento local (camada 'modelo pequeno'): desidratar sem LLM."""
from __future__ import annotations

from typing import Any


TYPE_HINTS = {
    "idade": "integer",
    "age": "integer",
    "quantidade": "integer",
    "qtd": "integer",
    "preco": "number",
    "valor": "number",
    "email": "string",
    "cpf": "string",
    "cnpj": "string",
    "telefone": "string",
    "ativo": "boolean",
    "habilitado": "boolean",
}


def _infer_type(name: str, sample: Any = None) -> str:
    key = name.lower().strip()
    if key in TYPE_HINTS:
        return TYPE_HINTS[key]
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int) and not isinstance(sample, bool):
        return "integer"
    if isinstance(sample, float):
        return "number"
    if isinstance(sample, list):
        return "array"
    if isinstance(sample, dict):
        return "object"
    if key.startswith("id") or key.endswith("_id") or key.endswith("Id"):
        return "string"
    return "string"


def dehydrate_figma(figma: dict[str, Any]) -> dict[str, Any]:
    """Extrai só inputs, ações e colunas de lista — sem metadados visuais."""
    inputs = []
    for item in figma.get("inputs", figma.get("fields", [])):
        if isinstance(item, str):
            inputs.append({"name": item, "type": _infer_type(item)})
        elif isinstance(item, dict):
            name = item.get("name") or item.get("id") or item.get("label", "field")
            inputs.append(
                {
                    "name": name,
                    "type": item.get("type") or _infer_type(name, item.get("value")),
                    "required": bool(item.get("required", False)),
                }
            )

    actions = []
    for btn in figma.get("buttons", figma.get("actions", [])):
        if isinstance(btn, str):
            actions.append({"id": btn})
        elif isinstance(btn, dict):
            actions.append(
                {
                    "id": btn.get("id") or btn.get("name") or btn.get("label"),
                    "method": btn.get("method"),
                    "path": btn.get("path") or btn.get("endpoint"),
                }
            )

    columns = []
    for col in figma.get("list", figma.get("table", figma.get("columns", []))):
        if isinstance(col, str):
            columns.append({"name": col, "type": _infer_type(col)})
        elif isinstance(col, dict):
            name = col.get("name") or col.get("id") or col.get("field")
            columns.append({"name": name, "type": col.get("type") or _infer_type(str(name))})

    return {"inputs": inputs, "actions": actions, "columns": columns}


def dehydrate_regras(regras: dict[str, Any]) -> dict[str, Any]:
    """Mantém condições, bloqueios e decisões — remove prosa."""
    out: dict[str, Any] = {
        "fluxo": regras.get("fluxo") or regras.get("flow") or regras.get("nome"),
        "happy": regras.get("happy_path") or regras.get("sucesso") or [],
        "bloqueios": [],
        "decisoes": regras.get("tabela_decisao") or regras.get("decisoes") or [],
    }

    for b in regras.get("bloqueios", regras.get("erros", regras.get("regras", []))):
        if isinstance(b, str):
            out["bloqueios"].append({"trigger": b, "status": 422})
        elif isinstance(b, dict):
            out["bloqueios"].append(
                {
                    "trigger": b.get("trigger") or b.get("quando") or b.get("condicao") or b.get("descricao"),
                    "status": int(b.get("status") or b.get("http") or _guess_status(b)),
                    "code": b.get("code") or b.get("codigo"),
                }
            )
    return out


def _guess_status(rule: dict[str, Any]) -> int:
    text = " ".join(str(v) for v in rule.values()).lower()
    if "auth" in text or "login" in text or "token" in text:
        return 401
    if "permiss" in text or "proibid" in text or "forbid" in text:
        return 403
    if "não encontr" in text or "nao encontr" in text or "not found" in text:
        return 404
    if "inválid" in text or "invalid" in text or "obrigat" in text:
        return 400
    return 422


def dehydrate_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mantém texto para compressão; remove path absoluto do estado público depois."""
    out: list[dict[str, Any]] = []
    for d in documents or []:
        out.append(
            {
                "name": d.get("name"),
                "ext": d.get("ext"),
                "lines": d.get("lines"),
                "chars": d.get("chars"),
                "est_tokens_raw": d.get("est_tokens_raw"),
                "text": d.get("text") or "",
            }
        )
    return out


def preprocess(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "tipo": raw["tipo"],
        "ui": dehydrate_figma(raw.get("figma") or {}),
        "regras": dehydrate_regras(raw.get("regras") or {}),
        "documents": dehydrate_documents(raw.get("documents") or []),
        "template": raw.get("template", ""),
    }
