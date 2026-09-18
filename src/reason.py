"""Raciocínio: monta pacote LLM (cacheável), dry-run local ou chamada `--live`."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from src.economia import MODELOS, custo_chamada
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
from src.hardening.claim_tools import (
    claude_tools,
    claim_tool_specs,
    dispatch_tool,
    openai_tools,
)
from src.hardening.input_scan import InputScanBlocked, scan_blobs
from src.tokenizer import TokenEstimate, observe_billable, provider_for_model

# Transporte HTTP injetável: (method, url, headers, body, timeout) → (status, body).
Transport = Callable[[str, str, dict[str, str], bytes, float], tuple[int, bytes]]

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
CLAUDE_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_LIVE_TIMEOUT_S = 90.0
DEFAULT_MAX_OUTPUT_TOKENS = 8192
MAX_TOOL_ROUNDS = 3

# Nomes curtos do config/economia → IDs de API do vendor.
_API_MODEL_IDS: dict[tuple[str, str], str] = {
    ("openai", "gpt-4o"): "gpt-4o",
    ("openai", "gpt-4o-mini"): "gpt-4o-mini",
    ("openai", "gpt-4.1"): "gpt-4.1",
    ("anthropic", "claude-sonnet"): "claude-sonnet-4-20250514",
    ("anthropic", "claude-haiku"): "claude-haiku-4-5-20251001",
}


class LiveApiError(RuntimeError):
    """Falha na chamada `--live`. O handler não deve gravar artefato parcial."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class LiveUsage:
    input_tokens: int
    output_tokens: int
    billable_tokens: int
    cache_read_tokens: int = 0
    cache_hit_ratio: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveResult:
    text: str
    provider: str
    model: str
    usage: LiveUsage
    response_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    tool_rounds: int = 0


def resolve_api_model(provider: str, model: str) -> str:
    key = (provider.lower().strip(), model.lower().strip())
    mapped = _API_MODEL_IDS.get(key)
    if mapped:
        return mapped
    return model.strip()


def env_api_key(provider: str) -> str | None:
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY") or None
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY") or None
    return None


def default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read() if hasattr(exc, "read") else b""
        return int(exc.code), payload
    except urllib.error.URLError as exc:
        raise LiveApiError(f"falha de rede na API ({url}): {exc}") from exc


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout: float,
    transport: Transport | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **headers}
    status, raw = (transport or default_transport)(method, url, hdrs, body, timeout)
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        raise LiveApiError(
            f"resposta não-JSON da API (HTTP {status})",
            status=status,
            body=text[:2000],
        ) from exc
    if status < 200 or status >= 300:
        err = data.get("error") if isinstance(data, dict) else None
        msg = ""
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("type") or "")
        elif isinstance(err, str):
            msg = err
        raise LiveApiError(
            msg or f"API HTTP {status}",
            status=status,
            body=text[:2000],
        )
    if not isinstance(data, dict):
        raise LiveApiError("resposta JSON inesperada (não-objeto)", status=status)
    return data


def _usage_from_openai(raw_usage: dict[str, Any] | None) -> LiveUsage:
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    details = usage.get("input_tokens_details")
    cached = 0
    if isinstance(details, dict):
        cached = int(details.get("cached_tokens") or 0)
    cached = cached or int(usage.get("cache_read_input_tokens") or 0)
    billable = input_tokens + output_tokens
    ratio = round(cached / input_tokens, 4) if input_tokens > 0 and cached > 0 else (
        0.0 if input_tokens > 0 else None
    )
    return LiveUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable,
        cache_read_tokens=cached,
        cache_hit_ratio=ratio,
        raw=dict(usage),
    )


def _usage_from_claude(raw_usage: dict[str, Any] | None) -> LiveUsage:
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cached = int(usage.get("cache_read_input_tokens") or 0)
    billable = input_tokens + output_tokens
    ratio = round(cached / input_tokens, 4) if input_tokens > 0 and cached > 0 else (
        0.0 if input_tokens > 0 else None
    )
    return LiveUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable,
        cache_read_tokens=cached,
        cache_hit_ratio=ratio,
        raw=dict(usage),
    )


def _merge_usage(parts: list[LiveUsage]) -> LiveUsage:
    if not parts:
        return LiveUsage(0, 0, 0)
    input_tokens = sum(p.input_tokens for p in parts)
    output_tokens = sum(p.output_tokens for p in parts)
    cached = sum(p.cache_read_tokens for p in parts)
    billable = sum(p.billable_tokens for p in parts)
    ratio = round(cached / input_tokens, 4) if input_tokens > 0 and cached > 0 else (
        0.0 if input_tokens > 0 else None
    )
    return LiveUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        billable_tokens=billable,
        cache_read_tokens=cached,
        cache_hit_ratio=ratio,
        raw={"rounds": [p.raw for p in parts]},
    )


def _openai_output_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in {
                    "output_text",
                    "text",
                }:
                    chunks.append(str(part.get("text") or ""))
        elif item.get("type") == "output_text":
            chunks.append(str(item.get("text") or ""))
    if chunks:
        return "".join(chunks).strip()
    # fallback legado chat-completions shape
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        return str(msg.get("content") or "").strip()
    return ""


def _openai_function_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"function_call", "tool_call"}:
            calls.append(item)
    return calls


def _claude_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            chunks.append(str(block.get("text") or ""))
    return "".join(chunks).strip()


def _claude_tool_uses(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        b
        for b in (data.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


def _price_for_model(model: str) -> dict[str, float]:
    if model in MODELOS:
        return MODELOS[model]
    short = model.lower()
    for key, preco in MODELOS.items():
        if key in short or short.startswith(key):
            return preco
    # fallback conservador (gpt-4o) só para telemetria — não inventa preço exato
    return MODELOS["gpt-4o"]


def build_live_telemetry(
    estimate: TokenEstimate | dict[str, Any] | None,
    live: LiveResult,
) -> dict[str, Any]:
    """Une estimado pré-chamada com billable/cache/custo reais do vendor."""
    if isinstance(estimate, TokenEstimate):
        base = observe_billable(estimate, live.usage.billable_tokens)
    elif isinstance(estimate, dict) and estimate.get("estimated") is not None:
        method = estimate.get("method") or "heuristic"
        if method not in ("official", "heuristic"):
            method = "heuristic"
        fake = TokenEstimate(
            tokens=int(estimate.get("estimated") or estimate.get("tokens") or 0),
            method=method,  # type: ignore[arg-type]
            provider=str(estimate.get("provider") or live.provider),
            model=str(estimate.get("model") or live.model),
            encoding=estimate.get("encoding"),
            fallback_reason=estimate.get("fallback_reason"),
        )
        base = observe_billable(fake, live.usage.billable_tokens)
    else:
        base = {
            "estimated": None,
            "method": None,
            "billable": live.usage.billable_tokens,
            "delta": None,
            "delta_pct": None,
            "provider": live.provider,
            "model": live.model,
        }
    preco = _price_for_model(live.model)
    cache_hit = float(live.usage.cache_hit_ratio or 0.0)
    cost = custo_chamada(
        live.usage.input_tokens,
        output_tokens=live.usage.output_tokens,
        preco=preco,
        cache_hit=cache_hit,
        cacheable_prefix=live.usage.input_tokens,
    )
    return {
        **base,
        "input_tokens": live.usage.input_tokens,
        "output_tokens": live.usage.output_tokens,
        "cache_read_tokens": live.usage.cache_read_tokens,
        "cache_hit": live.usage.cache_hit_ratio,
        "cost_usd": cost,
        "cost_kind": "observed_billing",
        "is_invoice": False,  # tabela local / billable observado ≠ fatura do vendor
        "live_provider": live.provider,
        "live_model": live.model,
        "response_id": live.response_id,
        "tool_rounds": live.tool_rounds,
    }


def call_openai_responses(
    package: dict[str, Any],
    *,
    model: str,
    api_key: str,
    claims: list[dict[str, Any]] | None = None,
    timeout: float = DEFAULT_LIVE_TIMEOUT_S,
    transport: Transport | None = None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> LiveResult:
    """OpenAI Responses API consumindo `package['openai']`."""
    openai_pkg = package.get("openai")
    if not isinstance(openai_pkg, dict):
        raise LiveApiError("llm_package sem bloco 'openai'")
    api_model = resolve_api_model("openai", model)
    usages: list[LiveUsage] = []
    response_id: str | None = None
    last_raw: dict[str, Any] = {}
    text = ""
    tool_rounds = 0

    payload: dict[str, Any] = {
        "model": api_model,
        "instructions": openai_pkg.get("instructions"),
        "input": openai_pkg.get("input"),
        "store": bool(openai_pkg.get("store", True)),
        "tools": openai_pkg.get("tools") or [],
        "max_output_tokens": max_output_tokens,
    }

    for round_i in range(MAX_TOOL_ROUNDS + 1):
        data = _http_json(
            "POST",
            OPENAI_RESPONSES_URL,
            {"Authorization": f"Bearer {api_key}"},
            payload,
            timeout=timeout,
            transport=transport,
        )
        last_raw = data
        response_id = str(data.get("id") or "") or response_id
        usages.append(_usage_from_openai(data.get("usage") if isinstance(data.get("usage"), dict) else None))
        text = _openai_output_text(data)
        calls = _openai_function_calls(data)
        if text and not calls:
            break
        if not calls:
            break
        if round_i >= MAX_TOOL_ROUNDS:
            break
        tool_rounds += 1
        outputs: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name") or call.get("function", {}).get("name") or "")
            args = call.get("arguments") or call.get("function", {}).get("arguments") or {}
            call_id = str(call.get("call_id") or call.get("id") or name)
            result = dispatch_tool(name, args, claims)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )
        payload = {
            "model": api_model,
            "previous_response_id": response_id,
            "input": outputs,
            "store": True,
        }

    if not text:
        raise LiveApiError(
            "OpenAI Responses não retornou texto de artefato",
            body=json.dumps(last_raw, ensure_ascii=False)[:2000],
        )
    return LiveResult(
        text=text,
        provider="openai",
        model=api_model,
        usage=_merge_usage(usages),
        response_id=response_id,
        raw=last_raw,
        tool_rounds=tool_rounds,
    )


def call_claude_messages(
    package: dict[str, Any],
    *,
    model: str,
    api_key: str,
    claims: list[dict[str, Any]] | None = None,
    timeout: float = DEFAULT_LIVE_TIMEOUT_S,
    transport: Transport | None = None,
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> LiveResult:
    """Anthropic Messages API consumindo `package['claude']`."""
    claude_pkg = package.get("claude")
    if not isinstance(claude_pkg, dict):
        raise LiveApiError("llm_package sem bloco 'claude'")
    api_model = resolve_api_model("anthropic", model)
    usages: list[LiveUsage] = []
    last_raw: dict[str, Any] = {}
    text = ""
    tool_rounds = 0
    messages = list(claude_pkg.get("messages") or [])
    system = claude_pkg.get("system")
    tools = claude_pkg.get("tools") or []

    for round_i in range(MAX_TOOL_ROUNDS + 1):
        payload: dict[str, Any] = {
            "model": api_model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools,
        }
        if system is not None:
            payload["system"] = system
        data = _http_json(
            "POST",
            CLAUDE_MESSAGES_URL,
            {
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            payload,
            timeout=timeout,
            transport=transport,
        )
        last_raw = data
        usages.append(_usage_from_claude(data.get("usage") if isinstance(data.get("usage"), dict) else None))
        text = _claude_text(data)
        tool_uses = _claude_tool_uses(data)
        stop = str(data.get("stop_reason") or "")
        if text and stop != "tool_use" and not tool_uses:
            break
        if not tool_uses:
            break
        if round_i >= MAX_TOOL_ROUNDS:
            break
        tool_rounds += 1
        messages = [
            *messages,
            {"role": "assistant", "content": data.get("content") or []},
        ]
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            name = str(block.get("name") or "")
            result = dispatch_tool(name, block.get("input") or {}, claims)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str(block.get("id") or name),
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    if not text:
        raise LiveApiError(
            "Claude Messages não retornou texto de artefato",
            body=json.dumps(last_raw, ensure_ascii=False)[:2000],
        )
    return LiveResult(
        text=text,
        provider="anthropic",
        model=api_model,
        usage=_merge_usage(usages),
        response_id=str(last_raw.get("id") or "") or None,
        raw=last_raw,
        tool_rounds=tool_rounds,
    )


def live_generate(
    package: dict[str, Any],
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    claims: list[dict[str, Any]] | None = None,
    timeout: float = DEFAULT_LIVE_TIMEOUT_S,
    transport: Transport | None = None,
) -> LiveResult:
    """Despacha para OpenAI Responses ou Claude Messages conforme o provider."""
    meta = package.get("meta") if isinstance(package.get("meta"), dict) else {}
    usage_hint = meta.get("token_usage") if isinstance(meta, dict) else None
    resolved_model = (
        model
        or (usage_hint or {}).get("model")
        or "gpt-4o"
    )
    resolved_provider = (
        (provider or "").strip().lower()
        or provider_for_model(str(resolved_model))
        or "openai"
    )
    if resolved_provider == "google":
        raise LiveApiError(
            "provider 'google' ainda não tem client --live; use openai ou anthropic"
        )
    if resolved_provider not in {"openai", "anthropic"}:
        raise LiveApiError(f"provider --live não suportado: {resolved_provider}")

    key = api_key or env_api_key(resolved_provider)
    if not key:
        env_name = "OPENAI_API_KEY" if resolved_provider == "openai" else "ANTHROPIC_API_KEY"
        raise LiveApiError(f"defina {env_name} para usar --live com {resolved_provider}")

    if resolved_provider == "openai":
        return call_openai_responses(
            package,
            model=str(resolved_model),
            api_key=key,
            claims=claims,
            timeout=timeout,
            transport=transport,
        )
    return call_claude_messages(
        package,
        model=str(resolved_model),
        api_key=key,
        claims=claims,
        timeout=timeout,
        transport=transport,
    )


def build_llm_package(
    context: dict[str, Any],
    *,
    claims: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    scan_inputs: bool = True,
) -> dict[str, Any]:
    """Pacote pronto p/ OpenAI Responses (previous_response_id) ou Claude cache_control."""
    system = context["system"]
    dynamic = context["dynamic"]
    if scan_inputs:
        report = scan_blobs(
            [("llm_package.dynamic", json.dumps(dynamic, ensure_ascii=False))]
        )
        if report.blocks:
            raise InputScanBlocked(report)
    claim_list = list(claims or [])
    tools = claim_tool_specs()
    return {
        "openai": {
            "instructions": system,
            "input": json.dumps(dynamic, ensure_ascii=False),
            "store": True,
            "tools": openai_tools(),
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
            "tools": claude_tools(),
        },
        "tools": tools,
        "meta": {
            "est_tokens": context.get("est_tokens"),
            "est_tokens_method": context.get("est_tokens_method"),
            "token_usage": context.get("token_usage"),
            "rag_stats": context.get("rag_stats"),
            "comando": dynamic.get("comando"),
            "run_id": run_id,
            "claim_index": {
                "count": len(claim_list),
                "ids": [str(c.get("id")) for c in claim_list if c.get("id")][:50],
            },
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
            "        BFF-->>FE: Error",
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
        .replace("{{documentacao}}", format_documentacao(eng))
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
        .replace("{{nfr_documentacao}}", format_documentacao(eng, with_ids=True))
        .replace("{{dependencias}}", "\n".join(deps) if deps else "- (nenhuma explícita)")
        .replace(
            "{{metricas}}",
            "- 100% dos RF cobertos por AC neste contexto\n"
            "- NFR-R/O/S/D do baseline na DoD\n"
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
