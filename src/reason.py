"""Raciocínio: monta pacote LLM (cacheável) ou dry-run determinístico sem API."""
from __future__ import annotations

import json
from typing import Any


def build_llm_package(context: dict[str, Any]) -> dict[str, Any]:
    """Pacote pronto p/ OpenAI Responses (previous_response_id) ou Claude cache_control."""
    system = context["system"]
    dynamic = context["dynamic"]
    return {
        "openai": {
            "instructions": system,
            "input": json.dumps(dynamic, ensure_ascii=False),
            "store": True,  # permite encadear via previous_response_id
        },
        "claude": {
            "system": [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(dynamic, ensure_ascii=False),
                }
            ],
        },
        "meta": {
            "est_tokens": context.get("est_tokens"),
            "rag_stats": context.get("rag_stats"),
            "comando": dynamic.get("comando"),
        },
    }


def dry_run_scaffold(tipo: str, ui: dict[str, Any], regras: dict[str, Any], template: str) -> str:
    """Preenche esqueleto sem LLM — útil p/ validar pipeline antes do teste com artefatos."""
    if tipo == "openapi":
        return _scaffold_openapi(ui, regras, template)
    if tipo == "mermaid":
        return _scaffold_mermaid(ui, regras, template)
    if tipo == "historia":
        return _scaffold_historia(ui, regras, template)
    raise ValueError(tipo)


def _scaffold_openapi(ui: dict, regras: dict, template: str) -> str:
    # marca placeholders; LLM/teste real completa paths
    props = {i["name"]: {"type": i["type"]} for i in ui.get("inputs", [])}
    cols = {c["name"]: {"type": c["type"]} for c in ui.get("columns", [])}
    marker = (
        "\n# --- DRY-RUN MARKERS ---\n"
        f"# request_props: {json.dumps(props, ensure_ascii=False)}\n"
        f"# response_cols: {json.dumps(cols, ensure_ascii=False)}\n"
        f"# bloqueios: {json.dumps(regras.get('bloqueios', []), ensure_ascii=False)}\n"
        f"# actions: {json.dumps(ui.get('actions', []), ensure_ascii=False)}\n"
    )
    return template.rstrip() + marker


def _scaffold_mermaid(ui: dict, regras: dict, template: str) -> str:
    action = (ui.get("actions") or [{}])[0]
    method = (action.get("method") or "POST").upper()
    path = action.get("path") or "/recurso"
    lines = [
        f"    FE->>BFF: {method} {path}",
        "    BFF->>API: forward",
        "    API-->>BFF: 200 OK",
        "    BFF-->>FE: payload",
    ]
    for b in regras.get("bloqueios") or []:
        lines += [
            f"    alt {b.get('trigger')}",
            f"        API-->>BFF: {b.get('status')}",
            f"        BFF-->>FE: Error",
            "    end",
        ]
    body = "\n".join(lines)
    return (
        template.replace("%% {{happy_path}}", body.split("alt")[0] if "alt" in body else body)
        .replace("%% {{alt_blocks}}", "\n".join(lines[4:]) if len(lines) > 4 else "")
    )


def _scaffold_historia(ui: dict, regras: dict, template: str) -> str:
    fluxo = regras.get("fluxo") or "Fluxo"
    criterios = []
    for b in regras.get("bloqueios") or []:
        criterios.append(
            f"- **Dado** condição de bloqueio\n"
            f"  **Quando** {b.get('trigger')}\n"
            f"  **Então** retornar HTTP {b.get('status')}"
        )
    if not criterios:
        criterios.append("- **Dado** dados válidos\n  **Quando** submeter\n  **Então** sucesso 200")
    deps = [f"- campo `{i['name']}` ({i['type']})" for i in ui.get("inputs", [])]
    return (
        template.replace("{{titulo}}", f"[BFF/MFE] {fluxo}")
        .replace("{{contexto}}", f"Implementar {fluxo} conforme UI e regras desidratadas.")
        .replace("{{criterios_bdd}}", "\n".join(criterios))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma)")
    )
