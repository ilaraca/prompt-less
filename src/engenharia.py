"""Defaults de engenharia (stack, NFRs) — baseline mínimo, extensível."""
from __future__ import annotations

from typing import Any


DEFAULT_ENGENHARIA: dict[str, Any] = {
    "version": 1,
    "stack": {"bff": ["(definir)"], "mfe": ["(definir)"]},
    "padroes": ["openapi-first"],
    "arquitetura": {"fluxo": "MFE -> BFF -> API Domínio", "contrato": "openapi"},
    "resiliencia": {
        "timeout_ms": 2000,
        "retry": {"max_attempts": 2, "backoff": "exponential"},
    },
    "observabilidade": {
        "logs": {
            "formato": "structured_json",
            "campos_minimos": ["timestamp", "level", "service", "correlation_id", "message"],
            "sem_pii": True,
        }
    },
    "seguranca": {"validar_input": True},
}


def dehydrate_engenharia(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza engenharia.yaml; preenche baseline se arquivo vazio/ausente."""
    src = {**DEFAULT_ENGENHARIA, **(raw or {})}
    # merge raso das seções conhecidas para não perder defaults parciais
    for key in ("stack", "arquitetura", "resiliencia", "observabilidade", "seguranca"):
        base = dict(DEFAULT_ENGENHARIA.get(key) or {})
        override = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(override, dict):
            merged = {**base, **override}
            # retry aninhado
            if key == "resiliencia" and isinstance(override.get("retry"), dict):
                merged["retry"] = {
                    **(base.get("retry") or {}),
                    **override["retry"],
                }
            if key == "observabilidade" and isinstance(override.get("logs"), dict):
                merged["logs"] = {
                    **(base.get("logs") or {}),
                    **override["logs"],
                }
            src[key] = merged
    if raw and isinstance(raw.get("padroes"), list):
        src["padroes"] = raw["padroes"]
    return {
        "version": src.get("version", 1),
        "stack": src.get("stack") or {},
        "padroes": src.get("padroes") or [],
        "arquitetura": src.get("arquitetura") or {},
        "resiliencia": src.get("resiliencia") or {},
        "observabilidade": src.get("observabilidade") or {},
        "seguranca": src.get("seguranca") or {},
    }


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (não definido)"


def format_stack(eng: dict[str, Any]) -> str:
    stack = eng.get("stack") or {}
    lines: list[str] = []
    for side in ("bff", "mfe", "api"):
        vals = stack.get(side)
        if isinstance(vals, list) and vals:
            lines.append(f"- **{side.upper()}:** {', '.join(str(v) for v in vals)}")
        elif isinstance(vals, str) and vals:
            lines.append(f"- **{side.upper()}:** {vals}")
    return "\n".join(lines) if lines else "- (definir em inputs/engenharia.yaml)"


def format_padroes(eng: dict[str, Any]) -> str:
    return _bullets([str(p) for p in (eng.get("padroes") or [])])


def format_arquitetura(eng: dict[str, Any]) -> str:
    arch = eng.get("arquitetura") or {}
    lines = []
    if arch.get("fluxo"):
        lines.append(f"- Fluxo: `{arch['fluxo']}`")
    if arch.get("contrato"):
        lines.append(f"- Contrato: `{arch['contrato']}`")
    for k, v in arch.items():
        if k in {"fluxo", "contrato"}:
            continue
        lines.append(f"- {k}: `{v}`")
    return "\n".join(lines) if lines else "- (definir)"


def format_resiliencia(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    r = eng.get("resiliencia") or {}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    lines = []
    prefix = "**NFR-R-01** " if with_ids else ""
    if r.get("timeout_ms") is not None:
        lines.append(f"- {prefix}Timeout: `{r['timeout_ms']}ms`".replace("  ", " "))
    if retry:
        p2 = "**NFR-R-02** " if with_ids else ""
        attempts = retry.get("max_attempts", "?")
        backoff = retry.get("backoff", "?")
        lines.append(f"- {p2}Retry: `{attempts}` tentativas, backoff `{backoff}`")
    if not lines:
        lines.append("- (baseline ausente — definir timeout/retry)")
    lines.append("- _(futuro: circuit breaker, idempotência, bulkhead)_")
    return "\n".join(lines)


def format_observabilidade(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    o = eng.get("observabilidade") or {}
    logs = o.get("logs") if isinstance(o.get("logs"), dict) else {}
    lines = []
    p1 = "**NFR-O-01** " if with_ids else ""
    if logs:
        fmt = logs.get("formato", "structured")
        campos = ", ".join(str(c) for c in (logs.get("campos_minimos") or []))
        lines.append(f"- {p1}Logs `{fmt}` com campos: {campos or '(mínimos a definir)'}")
        if logs.get("sem_pii"):
            p2 = "**NFR-O-02** " if with_ids else ""
            lines.append(f"- {p2}Não logar PII / dados sensíveis")
    if not lines:
        lines.append("- (baseline ausente — definir logs estruturados)")
    lines.append("- _(futuro: metrics, tracing, alerting)_")
    return "\n".join(lines)


def format_seguranca(eng: dict[str, Any], *, with_ids: bool = False) -> str:
    s = eng.get("seguranca") or {}
    lines = []
    p1 = "**NFR-S-01** " if with_ids else ""
    if s.get("validar_input"):
        lines.append(f"- {p1}Validar input na borda (BFF/API)")
    if not lines:
        lines.append("- (mínimo: validar input)")
    lines.append("- _(futuro: authn/authz explícitos, secrets, threat model)_")
    return "\n".join(lines)


def format_nfr_stack_arch(eng: dict[str, Any]) -> str:
    return "\n".join(
        [
            format_stack(eng),
            format_padroes(eng),
            format_arquitetura(eng),
        ]
    )


def rag_snippet(eng: dict[str, Any]) -> str:
    """Chunk curto p/ consolidated (sem dump do YAML)."""
    r = eng.get("resiliencia") or {}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    logs = (eng.get("observabilidade") or {}).get("logs") or {}
    return (
        f"eng stack_bff={','.join(str(x) for x in ((eng.get('stack') or {}).get('bff') or []))}"
        f" resiliencia timeout_ms={r.get('timeout_ms')} retry={retry.get('max_attempts')}"
        f" logs={logs.get('formato')} correlation_id=required"
    )
