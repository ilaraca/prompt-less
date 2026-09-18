"""Renderizadores determinísticos a partir do Canonical Spec."""
from __future__ import annotations

from typing import Any

from src.domain.spec import CanonicalSpec
from src.engenharia import (
    format_arquitetura,
    format_documentacao,
    format_nfr_stack_arch,
    format_observabilidade,
    format_padroes,
    format_resiliencia,
    format_seguranca,
    format_stack,
)
from src.renderers.mermaid import render_mermaid
from src.renderers.openapi import build_openapi_document, render_openapi

__all__ = [
    "build_openapi_document",
    "render_historia",
    "render_mermaid",
    "render_openapi",
    "render_prd",
]


def _fill(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def _bdd_from_spec(spec: CanonicalSpec) -> str:
    lines: list[str] = []
    for ac in spec.acceptance_criteria:
        lines.append(
            f"- **{ac.id}** _(← {ac.requirement_id})_\n"
            f"  **Dado** {ac.given}\n"
            f"  **Quando** {ac.when}\n"
            f"  **Então** {ac.then}"
        )
    return "\n".join(lines) if lines else "- _(sem AC)_"


def _rf_from_spec(spec: CanonicalSpec) -> str:
    lines = [f"- **{r.id}** {r.text}" for r in spec.requirements]
    return "\n".join(lines) if lines else "- _(sem RF)_"


def _provenance_md(spec: CanonicalSpec) -> str:
    used: list[str] = []
    seen: set[str] = set()
    for bucket in (spec.requirements, spec.acceptance_criteria, spec.errors):
        for item in bucket:
            for cid in item.source_claims or []:
                if cid not in seen:
                    seen.add(cid)
                    used.append(cid)
    by_id = {c.id: c for c in spec.claims}
    lines: list[str] = []
    for cid in used:
        claim = by_id.get(cid)
        if claim is None:
            lines.append(f"- `{cid}` _(claim ausente)_")
            continue
        loc = ""
        src = claim.sources[0] if claim.sources else None
        if src is not None:
            loc = f" — `{src.document}`"
            if src.selected_lines:
                loc += " L" + ",".join(str(n) for n in src.selected_lines)
            elif src.locator:
                loc += f" `{src.locator}`"
            elif src.section:
                loc += f" {src.section}"
        lines.append(f"- `{claim.id}` {claim.text}{loc}")
    return "\n".join(lines) if lines else "- _(sem claims utilizados)_"


def _operacao_md(op) -> str:
    """Ação do PRD alinhada ao IR — sem method/path/status inventado."""
    if op.method and op.path:
        linha = f"- **{op.id}** {op.method} {op.path}"
    else:
        linha = f"- **{op.id}** {op.name} — _(method/path não resolvidos no IR)_"
    status = op.resolved_success_status()
    if status is None:
        return f"{linha} → sucesso _(unresolved — requer revisão)_"
    return f"{linha} → HTTP {status}"


def _ownership_md(spec: CanonicalSpec) -> str:
    repos = []
    for v in (spec.repositories or {}).values():
        repos.extend(v or [])
    if not repos and spec.service_id in {"default", "_unassigned"}:
        return "- _(contexto único — sem mapa)_"
    nome = spec.service_name or spec.service_id
    lines = [f"- **Serviço:** `{spec.service_id}` — {nome}"]
    if repos:
        lines.append("- **Repos:** " + ", ".join(f"`{r}`" for r in repos))
    return "\n".join(lines)


def render_historia(
    spec: CanonicalSpec,
    template: str,
    *,
    engenharia: dict[str, Any] | None = None,
) -> str:
    eng = engenharia or {}
    titulo = spec.service_name or spec.service_id or "História"
    return _fill(
        template,
        {
            "titulo": titulo,
            "ownership": _ownership_md(spec),
            "contexto": f"Fluxo `{spec.service_id}` gerado a partir do Canonical Spec.",
            "criterios_bdd": _bdd_from_spec(spec),
            "estado_atual": "- _(índice não aplicado neste render)_",
            "gaps": "- _(sem gaps calculados)_",
            "stack": format_stack(eng),
            "padroes": format_padroes(eng),
            "arquitetura": format_arquitetura(eng),
            "resiliencia": format_resiliencia(eng),
            "observabilidade": format_observabilidade(eng),
            "seguranca": format_seguranca(eng),
            "documentacao": format_documentacao(eng),
            "dependencias": "- Canonical Spec validado",
            "fora_escopo": "- Itens não presentes no Canonical Spec",
            "proveniencia": _provenance_md(spec),
        },
    )


def render_prd(
    spec: CanonicalSpec,
    template: str,
    *,
    engenharia: dict[str, Any] | None = None,
    consolidated: str = "",
) -> str:
    eng = engenharia or {}
    titulo = spec.service_name or spec.service_id or "PRD"
    repos = []
    for v in (spec.repositories or {}).values():
        repos.extend(v or [])
    regras = "\n".join(
        f"- **{e.id}** {e.trigger} → HTTP {e.status}" for e in spec.errors
    ) or "- _(sem erros explícitos)_"
    return _fill(
        template,
        {
            "prd_id": f"prd-{spec.service_id}",
            "titulo": titulo,
            "artifacts_dir": "outputs",
            "service_id": spec.service_id,
            "service_nome": titulo,
            "repos_yaml": str(repos),
            "camadas_yaml": "{}",
            "problema": f"Especificar o serviço `{spec.service_id}` de forma rastreável.",
            "objetivo": "Entregar RF/AC/NFR a partir do Canonical Spec.",
            "non_goals": "- Fora do Canonical Spec",
            "personas": "- Usuário do fluxo",
            "escopo_in": _rf_from_spec(spec),
            "escopo_out": "- Não listado no spec",
            "requisitos_funcionais": _rf_from_spec(spec),
            "dados_entrada": "- _(ver UI / operações)_",
            "dados_saida": "- _(ver UI / operações)_",
            "acoes": "\n".join(_operacao_md(o) for o in spec.operations)
            or "- _(sem operações)_",
            "regras_negocio": regras,
            "criterios_bdd": _bdd_from_spec(spec),
            "nfr_stack_arch": format_nfr_stack_arch(eng),
            "nfr_resiliencia": format_resiliencia(eng, with_ids=True),
            "nfr_observabilidade": format_observabilidade(eng, with_ids=True),
            "nfr_seguranca": format_seguranca(eng, with_ids=True),
            "nfr_documentacao": format_documentacao(eng, with_ids=True),
            "estado_atual": "- _(índice não aplicado neste render)_",
            "gaps": "- _(sem gaps)_",
            "dependencias": "- Canonical Spec",
            "metricas": "- RF/AC cobertos no SDD",
            "riscos": "\n".join(f"- {q.text}" for q in spec.open_questions) or "- _(nenhum)_",
            "contexto_comprimido": consolidated or "_(vazio)_",
            "ownership": _ownership_md(spec),
            "proveniencia": _provenance_md(spec),
        },
    )
