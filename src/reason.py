"""Raciocínio: monta pacote LLM (cacheável) ou dry-run determinístico sem API."""
from __future__ import annotations

import json
from typing import Any

from src.engenharia import (
    format_arquitetura,
    format_nfr_stack_arch,
    format_observabilidade,
    format_padroes,
    format_resiliencia,
    format_seguranca,
    format_stack,
)


def build_llm_package(context: dict[str, Any]) -> dict[str, Any]:
    """Pacote pronto p/ OpenAI Responses (previous_response_id) ou Claude cache_control."""
    system = context["system"]
    dynamic = context["dynamic"]
    return {
        "openai": {
            "instructions": system,
            "input": json.dumps(dynamic, ensure_ascii=False),
            "store": True,
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
    engenharia: dict[str, Any] | None = None,
    servico: dict[str, Any] | None = None,
) -> str:
    eng = engenharia or {}
    svc = servico or {}
    if tipo == "openapi":
        return _scaffold_openapi(ui, regras, template)
    if tipo == "mermaid":
        return _scaffold_mermaid(ui, regras, template)
    if tipo == "historia":
        return _scaffold_historia(ui, regras, template, eng, svc)
    if tipo == "prd":
        return _scaffold_prd(ui, regras, template, eng, svc, consolidated=consolidated)
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
    for j, h in enumerate(regras.get("happy") or [], start=len(criterios) + 1):
        criterios.append(
            f"- **AC-{j:02d}**\n  **Dado** fluxo feliz\n  **Quando** {h}\n  **Então** sucesso"
        )
    return criterios


def _ownership_md(svc: dict) -> str:
    if not svc or not svc.get("id"):
        return "- _(contexto único — sem `mapa-servicos.yaml` ou `--context`)_"
    repos = svc.get("repos") or []
    camadas = svc.get("camadas") or {}
    if camadas:
        repo_lines = "\n".join(
            f"  - **{tier}:** " + ", ".join(f"`{r}`" for r in (lista or []))
            for tier, lista in camadas.items()
        )
    elif repos:
        repo_lines = "\n".join(f"  - `{r}`" for r in repos)
    else:
        repo_lines = "  - _(definir repos no mapa)_"
    return (
        f"- **Serviço:** `{svc.get('id')}` — {svc.get('nome') or svc.get('id')}\n"
        f"- **Repositórios:**\n{repo_lines}"
    )


SEM_INDICE = (
    "- _(sem índice de código — rode `python -m src.repo_index --workspace ~/dev/repos`)_"
)


def _estado_atual_md(svc: dict) -> str:
    """O que já existe nos repos do serviço, por extração estática."""
    idx = svc.get("indice") or {}
    if not idx:
        return SEM_INDICE

    linhas: list[str] = []
    rotas = idx.get("rotas") or []
    if rotas:
        linhas.append(f"**Endpoints existentes** ({len(rotas)}):")
        linhas.extend(f"- `{r}`" for r in rotas[:12])
        if len(rotas) > 12:
            linhas.append(f"- _(+{len(rotas) - 12} rotas — ver `state/repo_index.json`)_")
    else:
        linhas.append("**Endpoints existentes:** nenhum detectado (serviço novo?)")

    status = idx.get("status") or []
    if status:
        linhas.append("")
        linhas.append("**Códigos HTTP já tratados:** " + ", ".join(f"`{s}`" for s in status))

    entidades = (idx.get("classes") or [])[:10]
    if entidades:
        linhas.append("")
        linhas.append("**Entidades/classes:** " + ", ".join(f"`{c}`" for c in entidades))

    tabelas = idx.get("tabelas") or []
    if tabelas:
        linhas.append("**Tabelas:** " + ", ".join(f"`{t}`" for t in tabelas))

    campos = (idx.get("campos") or [])[:12]
    if campos:
        linhas.append("**Campos conhecidos:** " + ", ".join(f"`{c}`" for c in campos))

    stack = idx.get("stack") or []
    if stack:
        linhas.append("")
        linhas.append("**Stack detectada:** " + ", ".join(f"`{s}`" for s in stack))

    return "\n".join(linhas)


def _gaps_md(regras: dict, svc: dict) -> str:
    """Cruza status/regras do doc com o que o código já trata."""
    idx = svc.get("indice") or {}
    if not idx:
        return SEM_INDICE

    tratados = set(str(s) for s in (idx.get("status") or []))
    bloqueios = regras.get("bloqueios") or []
    if not bloqueios and not tratados:
        return "- _(sem regras de bloqueio para cruzar)_"

    linhas: list[str] = []
    for b in bloqueios:
        if not isinstance(b, dict):
            continue
        status = str(b.get("status") or "").strip()
        gatilho = b.get("trigger") or b.get("gatilho") or "regra"
        if status and status in tratados:
            linhas.append(f"- `{status}` — **já tratado no código**; validar gatilho: {gatilho}")
        elif status:
            linhas.append(f"- `{status}` — **não encontrado no código**; implementar: {gatilho}")
        else:
            linhas.append(f"- sem status declarado; definir contrato para: {gatilho}")

    esperados = {str(b.get("status")) for b in bloqueios if isinstance(b, dict)}
    sobrando = sorted(tratados - esperados - {"200", "201", "204"}, key=str)
    if sobrando:
        linhas.append(
            "- códigos no código sem regra correspondente no doc: "
            + ", ".join(f"`{s}`" for s in sobrando)
            + " _(regra implícita ou legado — confirmar)_"
        )
    return "\n".join(linhas) if linhas else "- _(nenhum gap identificado)_"


def _fluxo_nome(regras: dict, svc: dict) -> str:
    if svc.get("nome"):
        return str(svc["nome"])
    return regras.get("fluxo") or "Fluxo"


def _scaffold_openapi(ui: dict, regras: dict, template: str) -> str:
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


def _scaffold_historia(
    ui: dict, regras: dict, template: str, eng: dict, svc: dict
) -> str:
    fluxo = _fluxo_nome(regras, svc)
    sid = svc.get("id")
    title_prefix = f"[{sid}] " if sid and sid != "_unassigned" else "[BFF/MFE] "
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
    for r in svc.get("repos") or []:
        deps.append(f"- repo `{r}`")
    fora = [
        "- Mudanças de plataforma fora deste fluxo",
        "- Evoluções de NFR marcadas como _(futuro)_ em engenharia.yaml",
    ]
    if sid:
        fora.append(f"- Outros serviços fora de `{sid}` (ver `mapa-servicos.yaml`)")
    return (
        template.replace("{{titulo}}", f"{title_prefix}{fluxo}")
        .replace("{{ownership}}", _ownership_md(svc))
        .replace(
            "{{contexto}}",
            f"Implementar {fluxo} conforme UI, regras, docs do contexto"
            + (f" `{sid}`" if sid else "")
            + " e baseline de engenharia.",
        )
        .replace("{{criterios_bdd}}", "\n".join(criterios_hist))
        .replace("{{estado_atual}}", _estado_atual_md(svc))
        .replace("{{gaps}}", _gaps_md(regras, svc))
        .replace("{{stack}}", format_stack(eng))
        .replace("{{padroes}}", format_padroes(eng))
        .replace("{{arquitetura}}", format_arquitetura(eng))
        .replace("{{resiliencia}}", format_resiliencia(eng))
        .replace("{{observabilidade}}", format_observabilidade(eng))
        .replace("{{seguranca}}", format_seguranca(eng))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma)")
        .replace("{{fora_escopo}}", "\n".join(fora))
    )


def _scaffold_prd(
    ui: dict,
    regras: dict,
    template: str,
    eng: dict,
    svc: dict,
    *,
    consolidated: str = "",
) -> str:
    fluxo = _fluxo_nome(regras, svc)
    sid = svc.get("id") or "default"
    slug = "".join(ch if ch.isalnum() else "-" for ch in str(sid).lower()).strip("-") or "prd"
    prd_id = f"prd-{slug[:48]}"
    repos = svc.get("repos") or []
    repos_yaml = json.dumps(repos, ensure_ascii=False)
    camadas_yaml = json.dumps(svc.get("camadas") or {}, ensure_ascii=False)
    artifacts_dir = f"outputs/contextos/{sid}" if svc.get("id") else "outputs"

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
        "\n".join(
            f"- `{i['name']}` ({i['type']})" + (" — obrigatório" if i.get("required") else "")
            for i in ui.get("inputs", [])
        )
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
    deps.append("- baseline `inputs/engenharia.yaml` (stack + NFR v1)")
    deps.append("- mapa `inputs/mapa-servicos.yaml`")
    for r in repos:
        deps.append(f"- implementação em `{r}`")

    return (
        template.replace("{{prd_id}}", prd_id)
        .replace("{{titulo}}", fluxo)
        .replace("{{service_id}}", str(sid))
        .replace("{{service_nome}}", str(svc.get("nome") or sid))
        .replace("{{repos_yaml}}", repos_yaml)
        .replace("{{camadas_yaml}}", camadas_yaml)
        .replace("{{artifacts_dir}}", artifacts_dir)
        .replace("{{estado_atual}}", _estado_atual_md(svc))
        .replace("{{gaps}}", _gaps_md(regras, svc))
        .replace(
            "{{problema}}",
            f"Necessidade de especificar e entregar **{fluxo}**"
            + (f" (`{sid}`)" if svc.get("id") else "")
            + " com regras, contrato e NFRs mínimos para os repos donos.",
        )
        .replace(
            "{{objetivo}}",
            f"Viabilizar {fluxo} com RF/AC rastreáveis, ownership de microsserviço e baseline NFR até o SDD/Devin.",
        )
        .replace(
            "{{non_goals}}",
            "- Implementação de código de produção nesta pipeline\n"
            "- Design visual / handoff de UI pixel-perfect\n"
            "- Infraestrutura e deploy\n"
            "- Escopo de **outros** serviços do mapa\n"
            "- NFRs avançados marcados como futuro",
        )
        .replace(
            "{{personas}}",
            "- Usuário final da jornada\n- Time dono do(s) repo(s)\n- Tech Lead / Arquiteto (SDD)",
        )
        .replace(
            "{{escopo_in}}",
            f"- Contexto `{sid}` — {fluxo}\n"
            f"- Repos: {', '.join(f'`{r}`' for r in repos) or '(definir no mapa)'}\n"
            "- Validações/erros HTTP das regras aplicáveis\n"
            "- Baseline engenharia v1 (timeout/retry + logs)\n"
            "- Artefatos Prompt-less deste contexto",
        )
        .replace(
            "{{escopo_out}}",
            "- Outros microsserviços do `mapa-servicos.yaml`\n"
            "- Evoluções NFR além do baseline v1",
        )
        .replace("{{requisitos_funcionais}}", "\n".join(rfs))
        .replace("{{dados_entrada}}", entrada)
        .replace("{{dados_saida}}", saida)
        .replace("{{acoes}}", acoes)
        .replace("{{regras_negocio}}", regras_txt)
        .replace("{{criterios_bdd}}", "\n".join(_bdd_items(ui, regras)))
        .replace("{{nfr_stack_arch}}", format_nfr_stack_arch(eng))
        .replace("{{nfr_resiliencia}}", format_resiliencia(eng, with_ids=True))
        .replace("{{nfr_observabilidade}}", format_observabilidade(eng, with_ids=True))
        .replace("{{nfr_seguranca}}", format_seguranca(eng, with_ids=True))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma explícita)")
        .replace(
            "{{metricas}}",
            "- 100% dos RF cobertos por AC neste contexto\n"
            "- NFR-R/O/S do baseline na DoD\n"
            "- Ownership claro (service_id + repos)\n"
            "- Devin/SDD consome só `outputs/contextos/<id>/`",
        )
        .replace(
            "{{riscos}}",
            "- Texto sem marcadores/keywords → chunks em `_unassigned` ou drop\n"
            "- Mapa desatualizado classifica mal o serviço\n"
            "- Baseline NFR v1 é mínimo",
        )
        .replace(
            "{{contexto_comprimido}}",
            consolidated.strip() or "_(vazio — rode a pipeline com docs/regras para preencher)_",
        )
    )
