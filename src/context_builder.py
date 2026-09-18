"""Montagem de contexto ≤ budget — reserva conteúdo crítico + omissões recuperáveis."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.task_metrics import build_task_metrics
from src.tokenizer import HEURISTIC_CHARS_PER_TOKEN, TokenEstimate, estimate

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (ROOT / "prompts" / "system.compact.txt").read_text(encoding="utf-8")

CRITICAL_KINDS = frozenset({"requirement", "contract", "acceptance", "evidence"})
TEMPLATE_SOFT_CAP = 400


@dataclass
class CriticalItem:
    """Unidade crítica que não pode sumir silenciosamente no corte de budget."""

    id: str
    kind: str  # requirement | contract | acceptance | evidence
    text: str
    ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "ref": dict(self.ref),
            "recoverable": True,
        }


@dataclass
class BudgetReport:
    budget_tokens: int
    used_tokens: int
    status: str  # ok | trimmed | split_required | blocked
    included: list[str] = field(default_factory=list)
    omissions: list[dict[str, Any]] = field(default_factory=list)
    critical_omissions: list[dict[str, Any]] = field(default_factory=list)
    critical_coverage: dict[str, Any] = field(default_factory=dict)
    diagnosis: str | None = None
    split_plan: list[list[str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "budget_tokens": self.budget_tokens,
            "used_tokens": self.used_tokens,
            "status": self.status,
            "included": list(self.included),
            "omissions": list(self.omissions),
            "critical_omissions": list(self.critical_omissions),
            "critical_coverage": dict(self.critical_coverage),
        }
        if self.diagnosis:
            data["diagnosis"] = self.diagnosis
        if self.split_plan is not None:
            data["split_plan"] = [list(batch) for batch in self.split_plan]
        return data


def _payload(system: str, dynamic: dict[str, Any]) -> str:
    return system + str(dynamic)


def _count(system: str, dynamic: dict[str, Any]) -> TokenEstimate:
    return estimate(_payload(system, dynamic))


def _omission(
    *,
    item_id: str,
    reason: str,
    ref: dict[str, Any] | None = None,
    kind: str | None = None,
    recoverable: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item_id,
        "reason": reason,
        "recoverable": recoverable,
    }
    if kind:
        out["kind"] = kind
    if ref:
        out["ref"] = dict(ref)
    return out


def extract_critical_items(
    state: dict[str, Any] | None,
    rag: dict[str, Any] | None,
    spec: Any | None = None,
) -> list[CriticalItem]:
    """
    Extrai requisitos/contratos/aceites/evidências a preservar no budget.

    Prefere o Canonical Spec quando disponível; complementa com state/RAG.
    """
    items: list[CriticalItem] = []
    seen: set[str] = set()

    def _add(item: CriticalItem) -> None:
        if item.id in seen or not (item.text or "").strip():
            return
        if item.kind not in CRITICAL_KINDS:
            return
        seen.add(item.id)
        items.append(item)

    if spec is not None:
        for rf in getattr(spec, "requirements", None) or []:
            _add(
                CriticalItem(
                    id=str(rf.id),
                    kind="requirement",
                    text=str(rf.text or ""),
                    ref={
                        "source": "canonical_spec.requirements",
                        "subject_id": str(rf.id),
                        "claim_ids": list(getattr(rf, "source_claims", None) or []),
                    },
                )
            )
        for ac in getattr(spec, "acceptance_criteria", None) or []:
            text = (
                f"GIVEN {ac.given} WHEN {ac.when} THEN {ac.then}"
                if hasattr(ac, "given")
                else str(ac)
            )
            _add(
                CriticalItem(
                    id=str(ac.id),
                    kind="acceptance",
                    text=text,
                    ref={
                        "source": "canonical_spec.acceptance_criteria",
                        "subject_id": str(ac.id),
                        "requirement_id": str(getattr(ac, "requirement_id", "") or ""),
                        "claim_ids": list(getattr(ac, "source_claims", None) or []),
                    },
                )
            )
        for op in getattr(spec, "operations", None) or []:
            method = getattr(op, "method", None) or "?"
            path = getattr(op, "path", None) or "?"
            status = getattr(op, "success_status", None)
            status_val = getattr(status, "value", status) if status is not None else None
            oid = str(getattr(op, "id", None) or f"{method}:{path}")
            _add(
                CriticalItem(
                    id=oid,
                    kind="contract",
                    text=f"{method} {path} → {status_val}",
                    ref={
                        "source": "canonical_spec.operations",
                        "subject_id": oid,
                        "method": str(method),
                        "path": str(path),
                    },
                )
            )
        for err in getattr(spec, "errors", None) or []:
            eid = str(getattr(err, "id", None) or "")
            _add(
                CriticalItem(
                    id=eid or f"ERR-{len(seen)+1}",
                    kind="evidence",
                    text=str(getattr(err, "text", None) or getattr(err, "message", None) or err),
                    ref={
                        "source": "canonical_spec.errors",
                        "subject_id": eid,
                    },
                )
            )
        for claim in getattr(spec, "claims", None) or []:
            cid = str(getattr(claim, "id", None) or "")
            sources = []
            for src in getattr(claim, "sources", None) or []:
                if hasattr(src, "to_dict"):
                    sources.append(src.to_dict())
                elif isinstance(src, dict):
                    sources.append(src)
            _add(
                CriticalItem(
                    id=cid or f"CLM-{len(seen)+1}",
                    kind="evidence",
                    text=str(getattr(claim, "text", None) or ""),
                    ref={
                        "source": "canonical_spec.claims",
                        "subject_id": cid,
                        "sources": sources,
                    },
                )
            )

    state = state or {}
    for i, b in enumerate(state.get("bloqueios") or []):
        _add(
            CriticalItem(
                id=f"state.block.{i}",
                kind="requirement",
                text=f"block status={b.get('status')} trigger={b.get('trigger')}",
                ref={
                    "source": "state.bloqueios",
                    "index": i,
                    "locator": f"$.bloqueios[{i}]",
                },
            )
        )
    for i, a in enumerate(state.get("actions") or []):
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or f"action.{i}")
        _add(
            CriticalItem(
                id=f"state.action.{aid}",
                kind="contract",
                text=f"{a.get('method') or '?'}{a.get('path') or ''} ({aid})",
                ref={
                    "source": "state.actions",
                    "index": i,
                    "action_id": aid,
                    "locator": f"$.actions[{i}]",
                },
            )
        )

    rag = rag or {}
    for claim in rag.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("id") or "")
        _add(
            CriticalItem(
                id=cid or f"rag.claim.{len(seen)+1}",
                kind="evidence",
                text=str(claim.get("text") or ""),
                ref={
                    "source": "rag.claims",
                    "subject_id": cid,
                    "sources": list(claim.get("sources") or []),
                    "chunk_id": claim.get("chunk_id"),
                },
            )
        )

    return items


def _critical_blob(items: list[CriticalItem]) -> str:
    if not items:
        return ""
    lines = [f"[{it.kind}:{it.id}] {it.text}" for it in items]
    return "\n".join(lines)


def _coverage(items: list[CriticalItem], included_ids: set[str]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = {}
    for kind in sorted(CRITICAL_KINDS):
        total = [it for it in items if it.kind == kind]
        kept = [it for it in total if it.id in included_ids]
        by_kind[kind] = {"total": len(total), "included": len(kept)}
    return {
        "by_kind": by_kind,
        "total": len(items),
        "included": len(included_ids & {it.id for it in items}),
        "complete": all(it.id in included_ids for it in items),
    }


def _estimate_item_tokens(item: CriticalItem) -> int:
    return max(1, estimate(f"[{item.kind}:{item.id}] {item.text}").tokens)


def plan_critical_split(
    items: list[CriticalItem],
    *,
    budget_tokens: int,
    overhead_tokens: int,
) -> list[list[CriticalItem]] | None:
    """Empacota itens críticos em lotes que cabem no budget; None se impossível."""
    usable = budget_tokens - overhead_tokens
    if usable <= 0 or not items:
        return None
    sizes = {it.id: _estimate_item_tokens(it) for it in items}
    if any(sizes[it.id] > usable for it in items):
        return None
    batches: list[list[CriticalItem]] = []
    current: list[CriticalItem] = []
    used = 0
    for it in items:
        need = sizes[it.id] + (1 if current else 0)
        if current and used + need > usable:
            batches.append(current)
            current = [it]
            used = sizes[it.id]
        else:
            current.append(it)
            used += need
    if current:
        batches.append(current)
    return batches if batches else None


def _fit_to_budget(
    dynamic: dict[str, Any],
    budget_tokens: int,
    *,
    critical_items: list[CriticalItem] | None = None,
) -> tuple[TokenEstimate, BudgetReport]:
    """
    Encaixa no teto reservando conteúdo crítico.

    Não corta RF/AC/contratos/evidências. Omissões não-críticas têm motivo +
    ref recuperável. Excesso do mínimo crítico → split_required ou blocked.
    """
    items = list(critical_items or [])
    critical_text = _critical_blob(items)
    dynamic["critical"] = critical_text
    included_ids = {it.id for it in items}
    omissions: list[dict[str, Any]] = []
    included_labels = [f"{it.kind}:{it.id}" for it in items]

    # Baseline: system + comando + state + critical (sem template/consolidado)
    # Só mede overhead separado quando há itens críticos a proteger.
    if items:
        probe = {
            "comando": dynamic.get("comando"),
            "state": dynamic.get("state") or {},
            "critical": critical_text,
            "contexto_comprimido": "",
            "template": "",
        }
        overhead = _count(SYSTEM, probe)
        if overhead.tokens > budget_tokens:
            # tenta split
            split = plan_critical_split(
                items, budget_tokens=budget_tokens, overhead_tokens=_count(
                    SYSTEM,
                    {
                        "comando": dynamic.get("comando"),
                        "state": dynamic.get("state") or {},
                        "critical": "",
                        "contexto_comprimido": "",
                        "template": "",
                    },
                ).tokens
            )
            if split and len(split) > 1:
                dynamic["contexto_comprimido"] = ""
                dynamic["template"] = ""
                dynamic["critical"] = _critical_blob(split[0])
                kept = {it.id for it in split[0]}
                critical_omissions = [
                    _omission(
                        item_id=it.id,
                        reason="split_required",
                        ref=it.ref,
                        kind=it.kind,
                    )
                    for it in items
                    if it.id not in kept
                ]
                est = _count(SYSTEM, dynamic)
                report = BudgetReport(
                    budget_tokens=budget_tokens,
                    used_tokens=est.tokens,
                    status="split_required",
                    included=[f"{it.kind}:{it.id}" for it in split[0]],
                    omissions=[],
                    critical_omissions=critical_omissions,
                    critical_coverage=_coverage(items, kept),
                    diagnosis=(
                        f"mínimo crítico ({overhead.tokens} tok) excede budget "
                        f"({budget_tokens}); dividir em {len(split)} lote(s)"
                    ),
                    split_plan=[[it.id for it in batch] for batch in split],
                )
                return est, report

            critical_omissions = [
                _omission(
                    item_id=it.id,
                    reason="critical_budget_exceeded",
                    ref=it.ref,
                    kind=it.kind,
                )
                for it in items
            ]
            dynamic["contexto_comprimido"] = ""
            dynamic["template"] = ""
            est = _count(SYSTEM, dynamic)
            report = BudgetReport(
                budget_tokens=budget_tokens,
                used_tokens=est.tokens,
                status="blocked",
                included=included_labels,
                omissions=[],
                critical_omissions=critical_omissions,
                critical_coverage=_coverage(items, included_ids),
                diagnosis=(
                    f"conteúdo crítico mínimo ({overhead.tokens} tok) não cabe no "
                    f"budget ({budget_tokens}); bloqueado com diagnóstico"
                ),
            )
            return est, report

    # Crítico cabe (ou não há crítico): encaixa template e consolidado no restante
    est = _count(SYSTEM, dynamic)
    status = "ok"
    if est.tokens <= budget_tokens:
        return est, BudgetReport(
            budget_tokens=budget_tokens,
            used_tokens=est.tokens,
            status="ok",
            included=included_labels + ["template", "contexto_comprimido"],
            omissions=[],
            critical_omissions=[],
            critical_coverage=_coverage(items, included_ids),
        )

    template = str(dynamic.get("template") or "")
    if len(template) > TEMPLATE_SOFT_CAP:
        omitted_tail = template[TEMPLATE_SOFT_CAP:]
        dynamic["template"] = template[:TEMPLATE_SOFT_CAP] + "\n# …template truncado p/ budget"
        omissions.append(
            _omission(
                item_id="template",
                reason="budget_exceeded_non_critical",
                ref={
                    "source": "dynamic.template",
                    "chars_omitted": len(omitted_tail),
                    "recoverable": True,
                    "full_length": len(template),
                },
                kind="template",
            )
        )
        status = "trimmed"
        est = _count(SYSTEM, dynamic)
        if est.tokens <= budget_tokens:
            return est, BudgetReport(
                budget_tokens=budget_tokens,
                used_tokens=est.tokens,
                status=status,
                included=included_labels + ["template_partial", "contexto_comprimido"],
                omissions=omissions,
                critical_omissions=[],
                critical_coverage=_coverage(items, included_ids),
            )

    cons = str(dynamic.get("contexto_comprimido") or "")
    if cons and est.tokens > budget_tokens:
        overflow = est.tokens - budget_tokens
        cut = max(0, len(cons) - overflow * HEURISTIC_CHARS_PER_TOKEN)
        # nunca zerar consolidado se ainda houver folga após crítico — mas
        # garantir que critical[] permanece intacto (já está em dynamic["critical"])
        omitted = cons[cut:]
        dynamic["contexto_comprimido"] = cons[:cut] + ("…" if cut < len(cons) else "")
        if omitted:
            omissions.append(
                _omission(
                    item_id="contexto_comprimido",
                    reason="budget_exceeded_non_critical",
                    ref={
                        "source": "rag.consolidated",
                        "chars_omitted": len(omitted),
                        "chars_kept": cut,
                        "recoverable": True,
                        "hint": "recuperar via search_claims/get_claim ou re-rag",
                    },
                    kind="consolidated",
                )
            )
            status = "trimmed"
        est = _count(SYSTEM, dynamic)

    # Se ainda estoura, remove consolidado residual sem tocar critical nem o
    # template já soft-truncado (compatível com o corte legado marcado).
    if est.tokens > budget_tokens and dynamic.get("contexto_comprimido"):
        cons_left = str(dynamic.get("contexto_comprimido") or "")
        dynamic["contexto_comprimido"] = ""
        if cons_left:
            omissions.append(
                _omission(
                    item_id="contexto_comprimido",
                    reason="budget_exceeded_non_critical",
                    ref={
                        "source": "rag.consolidated",
                        "chars_omitted": len(cons_left),
                        "chars_kept": 0,
                        "recoverable": True,
                    },
                    kind="consolidated",
                )
            )
            status = "trimmed"
        est = _count(SYSTEM, dynamic)

    # Ainda acima com só crítico? → split/block (não cortar critical)
    if est.tokens > budget_tokens and items:
        split = plan_critical_split(
            items,
            budget_tokens=budget_tokens,
            overhead_tokens=_count(
                SYSTEM,
                {
                    "comando": dynamic.get("comando"),
                    "state": dynamic.get("state") or {},
                    "critical": "",
                    "contexto_comprimido": "",
                    "template": "",
                },
            ).tokens,
        )
        if split and len(split) > 1:
            kept = {it.id for it in split[0]}
            dynamic["critical"] = _critical_blob(split[0])
            critical_omissions = [
                _omission(
                    item_id=it.id,
                    reason="split_required",
                    ref=it.ref,
                    kind=it.kind,
                )
                for it in items
                if it.id not in kept
            ]
            est = _count(SYSTEM, dynamic)
            return est, BudgetReport(
                budget_tokens=budget_tokens,
                used_tokens=est.tokens,
                status="split_required",
                included=[f"{it.kind}:{it.id}" for it in split[0]],
                omissions=omissions,
                critical_omissions=critical_omissions,
                critical_coverage=_coverage(items, kept),
                diagnosis=(
                    f"após reservar crítico, payload ainda excede budget; "
                    f"dividir em {len(split)} lote(s)"
                ),
                split_plan=[[it.id for it in batch] for batch in split],
            )
        critical_omissions = [
            _omission(
                item_id=it.id,
                reason="critical_budget_exceeded",
                ref=it.ref,
                kind=it.kind,
            )
            for it in items
        ]
        return est, BudgetReport(
            budget_tokens=budget_tokens,
            used_tokens=est.tokens,
            status="blocked",
            included=included_labels,
            omissions=omissions,
            critical_omissions=critical_omissions,
            critical_coverage=_coverage(items, included_ids),
            diagnosis=(
                f"conteúdo crítico ({est.tokens} tok) permanece acima do budget "
                f"({budget_tokens}) após remover não-crítico"
            ),
        )

    labels = included_labels[:]
    if dynamic.get("template"):
        labels.append("template" if status == "ok" else "template_partial")
    if dynamic.get("contexto_comprimido"):
        labels.append("contexto_comprimido")
    return est, BudgetReport(
        budget_tokens=budget_tokens,
        used_tokens=est.tokens,
        status=status,
        included=labels,
        omissions=omissions,
        critical_omissions=[],
        critical_coverage=_coverage(items, included_ids),
    )


def build_context(
    tipo: str,
    state: dict[str, Any],
    rag: dict[str, Any],
    template: str,
    budget_tokens: int = 2000,
    *,
    spec: Any | None = None,
    attempts: int = 1,
) -> dict[str, Any]:
    """
    Prefixo estável (cacheável) + payload dinâmico com reserva de crítico.

    Retorna `budget_report` (omissões/diagnóstico) e `task_metrics` com
    `attempts` e custo marcado como estimativa (não fatura).
    """
    critical_items = extract_critical_items(state, rag, spec)
    dynamic: dict[str, Any] = {
        "comando": f"Gerar {tipo}",
        "state": state,
        "contexto_comprimido": rag.get("consolidated", ""),
        "template": template,
        "critical": "",
    }

    est, report = _fit_to_budget(
        dynamic, budget_tokens, critical_items=critical_items
    )
    usage = est.to_telemetry()
    # reforça: estimativa pré-chamada não é fatura
    usage["is_invoice"] = False
    usage["cost_kind"] = "estimate"

    metrics = build_task_metrics(
        attempts=attempts,
        duration_ms={},
        token_usage=usage,
        phases={},
    )

    return {
        "system": SYSTEM,  # prefixo estável → prompt caching
        "dynamic": dynamic,
        "est_tokens": est.tokens,
        "est_tokens_method": est.method,
        "token_usage": usage,
        "budget_report": report.to_dict(),
        "budget_status": report.status,
        "omissions": list(report.omissions),
        "critical_items": [it.to_dict() for it in critical_items],
        "task_metrics": metrics,
        "rag_stats": {
            "raw": rag.get("est_tokens_raw"),
            "compressed": rag.get("est_tokens_compressed"),
            "semantic": rag.get("est_tokens_semantic"),
            "hybrid": rag.get("hybrid"),
            "method": est.method,
            "docs": (rag.get("documents") or {}).get("docs"),
            "doc_reduction_pct": (rag.get("documents") or {}).get("reduction_pct"),
        },
    }
