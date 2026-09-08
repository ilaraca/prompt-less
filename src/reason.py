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


def dry_run_scaffold(
    tipo: str,
    ui: dict[str, Any],
    regras: dict[str, Any],
    template: str,
    *,
    consolidated: str = "",
) -> str:
    """Preenche esqueleto sem LLM — útil p/ validar pipeline antes do teste com artefatos."""
    if tipo == "openapi":
        return _scaffold_openapi(ui, regras, template)
    if tipo == "mermaid":
        return _scaffold_mermaid(ui, regras, template)
    if tipo == "historia":
        return _scaffold_historia(ui, regras, template)
    if tipo == "prd":
        return _scaffold_prd(ui, regras, template, consolidated=consolidated)
    raise ValueError(tipo)


def _bdd_items(ui: dict, regras: dict) -> list[str]:
    criterios = []
    for i, b in enumerate(regras.get("bloqueios") or [], start=1):
        criterios.append(
            f"- **AC-{i:02d}**\n"
            f"  **Dado** condição de bloqueio\n"
            f"  **Quando** {b.get('trigger')}\n"
            f"  **Então** retornar HTTP {b.get('status')}"
        )
    if not criterios:
        criterios.append(
            "- **AC-01**\n  **Dado** dados válidos\n  **Quando** submeter\n  **Então** sucesso 200"
        )
    # happy path explícito se houver
    for j, h in enumerate(regras.get("happy") or [], start=len(criterios) + 1):
        criterios.append(
            f"- **AC-{j:02d}**\n  **Dado** fluxo feliz\n  **Quando** {h}\n  **Então** sucesso"
        )
    return criterios


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
    criterios_hist = []
    for b in regras.get("bloqueios") or []:
        criterios_hist.append(
            f"- **Dado** condição de bloqueio\n"
            f"  **Quando** {b.get('trigger')}\n"
            f"  **Então** retornar HTTP {b.get('status')}"
        )
    if not criterios_hist:
        criterios_hist = [
            "- **Dado** dados válidos\n  **Quando** submeter\n  **Então** sucesso 200"
        ]
    deps = [f"- campo `{i['name']}` ({i['type']})" for i in ui.get("inputs", [])]
    return (
        template.replace("{{titulo}}", f"[BFF/MFE] {fluxo}")
        .replace("{{contexto}}", f"Implementar {fluxo} conforme UI e regras desidratadas.")
        .replace("{{criterios_bdd}}", "\n".join(criterios_hist))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma)")
    )


def _scaffold_prd(
    ui: dict, regras: dict, template: str, *, consolidated: str = ""
) -> str:
    fluxo = regras.get("fluxo") or "Fluxo"
    slug = "".join(ch if ch.isalnum() else "-" for ch in fluxo.lower()).strip("-") or "prd"
    prd_id = f"prd-{slug[:48]}"

    rfs = []
    for i, b in enumerate(regras.get("bloqueios") or [], start=1):
        rfs.append(
            f"- **RF-{i:02d}** Validar: {b.get('trigger')} → HTTP {b.get('status')}"
            + (f" (`{b.get('code')}`)" if b.get("code") else "")
        )
    for i, d in enumerate(regras.get("decisoes") or [], start=len(rfs) + 1):
        if isinstance(d, dict):
            quando = d.get("quando") or d.get("when") or d
            entao = d.get("entao") or d.get("then") or ""
            rfs.append(f"- **RF-{i:02d}** Decisão: quando {quando} → então {entao}".strip())
        else:
            rfs.append(f"- **RF-{i:02d}** Decisão: {d}")
    if not rfs:
        rfs.append("- **RF-01** Permitir submissão com dados válidos (HTTP 200)")

    entrada = (
        "\n".join(f"- `{i['name']}` ({i['type']})" + (" — obrigatório" if i.get("required") else "") for i in ui.get("inputs", []))
        or "- (não informado no Figma)"
    )
    saida = (
        "\n".join(f"- `{c['name']}` ({c['type']})" for c in ui.get("columns", []))
        or "- (não informado no Figma)"
    )
    acoes = (
        "\n".join(
            f"- `{a.get('id')}` {(a.get('method') or '').upper()} `{a.get('path') or ''}`".strip()
            for a in ui.get("actions", [])
        )
        or "- (não informado no Figma)"
    )
    regras_txt = (
        "\n".join(
            f"- {b.get('trigger')} → `{b.get('status')}`"
            + (f" / `{b.get('code')}`" if b.get("code") else "")
            for b in (regras.get("bloqueios") or [])
        )
        or "- (sem bloqueios explícitos)"
    )
    deps = [f"- campo UI `{i['name']}` ({i['type']})" for i in ui.get("inputs", [])]
    for a in ui.get("actions") or []:
        if a.get("path"):
            deps.append(f"- endpoint `{(a.get('method') or 'POST').upper()} {a.get('path')}`")

    return (
        template.replace("{{prd_id}}", prd_id)
        .replace("{{titulo}}", fluxo)
        .replace(
            "{{problema}}",
            f"Necessidade de especificar e entregar o fluxo **{fluxo}** com regras e contrato claros para implementação BFF/MFE.",
        )
        .replace(
            "{{objetivo}}",
            f"Viabilizar {fluxo} com validação de regras de negócio, contrato de dados e critérios BDD rastreáveis até o SDD.",
        )
        .replace(
            "{{non_goals}}",
            "- Implementação de código de produção\n"
            "- Design visual / handoff de UI pixel-perfect\n"
            "- Infraestrutura e deploy",
        )
        .replace("{{personas}}", "- Usuário final da jornada\n- Time BFF/MFE\n- Tech Lead / Arquiteto (SDD)")
        .replace(
            "{{escopo_in}}",
            f"- Fluxo `{fluxo}`\n- Validações e erros HTTP das regras\n- Campos e ações da UI\n- Artefatos Prompt-less (história, OpenAPI, sequência)",
        )
        .replace(
            "{{escopo_out}}",
            "- Features adjacentes não citadas nas regras\n- Otimizações de performance não especificadas",
        )
        .replace("{{requisitos_funcionais}}", "\n".join(rfs))
        .replace("{{dados_entrada}}", entrada)
        .replace("{{dados_saida}}", saida)
        .replace("{{acoes}}", acoes)
        .replace("{{regras_negocio}}", regras_txt)
        .replace("{{criterios_bdd}}", "\n".join(_bdd_items(ui, regras)))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma explícita)")
        .replace(
            "{{metricas}}",
            "- 100% dos RF cobertos por AC\n"
            "- Contrato OpenAPI alinhado às seções 7–8\n"
            "- Sequência Mermaid cobre happy path + bloqueios",
        )
        .replace(
            "{{riscos}}",
            "- Insumos incompletos (Figma/regras) → RF/AC parciais\n"
            "- Docs longos sem sinais lexicais podem omitir requisitos no contexto comprimido\n"
            "- OpenAPI/Mermaid ainda não gerados nesta execução: SDD deve regenerar ou apontar versões",
        )
        .replace(
            "{{contexto_comprimido}}",
            consolidated.strip() or "_(vazio — rode a pipeline com docs/regras para preencher)_",
        )
    )