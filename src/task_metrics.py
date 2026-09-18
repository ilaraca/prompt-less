"""Métricas de tarefa: tentativas, duração e custo sem misturar estimativa com fatura."""
from __future__ import annotations

from typing import Any


def classify_cost_kind(
    *,
    billable: int | None,
    observed_billing: dict[str, Any] | None = None,
) -> str:
    """`estimate` pré-chamada vs `observed_billing` pós-vendor — nunca `invoice`."""
    if observed_billing is not None or billable is not None:
        return "observed_billing"
    return "estimate"


def build_cost_section(
    token_usage: dict[str, Any] | None = None,
    *,
    cost_usd: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Seção de custo explícita: estimativa ≠ fatura do vendor.

    `is_invoice` é sempre False aqui — mesmo `cost_usd` de tabela local é
    referência, não cobrança. `billable` observado só marca `observed_billing`.
    """
    usage = dict(token_usage or {})
    billable = usage.get("billable")
    if billable is not None:
        try:
            billable = int(billable)
        except (TypeError, ValueError):
            billable = None
    kind = classify_cost_kind(
        billable=billable,
        observed_billing=usage.get("observed_billing"),
    )
    estimated = usage.get("estimated")
    if estimated is None:
        estimated = usage.get("tokens")
    return {
        "kind": kind,
        "is_invoice": False,
        "estimated_tokens": estimated,
        "observed_billable_tokens": billable,
        "method": usage.get("method"),
        "label": usage.get("label"),
        "delta": usage.get("delta"),
        "cost_usd_reference": cost_usd or usage.get("cost_usd"),
        "note": (
            "estimativa pré-chamada; não é fatura"
            if kind == "estimate"
            else "uso/cobrança observados do vendor; cost_usd é tabela local de referência, não fatura"
        ),
    }


def build_task_metrics(
    *,
    attempts: int = 1,
    duration_ms: dict[str, Any] | None = None,
    token_usage: dict[str, Any] | None = None,
    cost_usd: dict[str, Any] | None = None,
    phases: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Métricas agregadas da tarefa (contexto, validação, reparo).

    `attempts` é obrigatório no contrato; duração inclui fases quando
    fornecidas (validation/repair/total).
    """
    dur = dict(duration_ms or {})
    ph = dict(phases or {})
    if ph:
        for key in ("validation_ms", "repair_ms", "context_ms", "total_ms"):
            if key in ph and key not in dur:
                dur[key] = ph[key]
        if "total_ms" not in dur:
            parts = [
                int(ph[k])
                for k in ("validation_ms", "repair_ms", "context_ms")
                if ph.get(k) is not None
            ]
            if parts:
                dur["total_ms"] = sum(parts)
    metrics: dict[str, Any] = {
        "attempts": max(1, int(attempts)),
        "duration_ms": dur,
        "cost": build_cost_section(token_usage, cost_usd=cost_usd),
    }
    if ph:
        metrics["phases"] = ph
    if extra:
        metrics.update(extra)
    return metrics
