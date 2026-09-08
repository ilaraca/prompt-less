"""
Calculadora de economia de tokens/custo — Prompt-less vs. abordagem ingenua.

Compara o que iria para o LLM **sem** compressão (docs brutos + system verboso +
histórico + tools longas) com o pacote que a pipeline realmente monta.

  # Mede os inputs/ atuais e projeta custo
  python -m src.economia
  python -m src.economia --runs-mes 80 --modelo gpt-4o
  python -m src.economia --modelo claude-sonnet --cache-hit 0.6

  # Cenário hipotético (sem ler inputs/)
  python -m src.economia --what-if --linhas 3000 --runs-mes 40

  # JSON para dashboard/CI
  python -m src.economia --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.context_builder import build_context  # noqa: E402
from src.ingest import ARTIFACT_TEMPLATES, load_inputs  # noqa: E402
from src.preprocess import preprocess  # noqa: E402
from src.rag_compress import compress_rag  # noqa: E402


def _state_sem_gravar(data: dict[str, Any]) -> dict[str, Any]:
    """Mesmo slim do state_store, sem tocar disco (calculadora é read-only)."""
    docs_meta = [
        {
            "name": d.get("name"),
            "lines": d.get("lines"),
            "est_tokens_raw": d.get("est_tokens_raw"),
        }
        for d in (data.get("documents") or [])
    ]
    return {
        "tipo": data.get("tipo"),
        "fluxo": (data.get("regras") or {}).get("fluxo"),
        "inputs": [i.get("name") for i in (data.get("ui") or {}).get("inputs", [])],
        "actions": (data.get("ui") or {}).get("actions", []),
        "bloqueios": (data.get("regras") or {}).get("bloqueios", []),
        "engenharia": {
            "version": (data.get("engenharia") or {}).get("version"),
            "stack": (data.get("engenharia") or {}).get("stack"),
            "resiliencia": (data.get("engenharia") or {}).get("resiliencia"),
            "observabilidade": {
                "logs": ((data.get("engenharia") or {}).get("observabilidade") or {}).get("logs")
            },
        },
        "documents": docs_meta,
        "previous_actions": data.get("previous_actions", []),
        "status": data.get("status", "ready"),
    }

# ---------------------------------------------------------------------------
# Preços de referência (USD / 1M tokens) — atualize conforme a tabela do vendor.
# Input = prompt; Output = completion. Cache = leitura de prefixo cacheado.
# ---------------------------------------------------------------------------
MODELOS: dict[str, dict[str, float]] = {
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
        "cache": 1.25,  # cached input (~50% do input na OpenAI)
        "label": "OpenAI GPT-4o",
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cache": 0.075,
        "label": "OpenAI GPT-4o mini",
    },
    "gpt-4.1": {
        "input": 2.00,
        "output": 8.00,
        "cache": 0.50,
        "label": "OpenAI GPT-4.1",
    },
    "claude-sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache": 0.30,  # cache read Claude
        "label": "Anthropic Claude Sonnet",
    },
    "claude-haiku": {
        "input": 0.80,
        "output": 4.00,
        "cache": 0.08,
        "label": "Anthropic Claude Haiku",
    },
    "gemini-flash": {
        "input": 0.15,
        "output": 0.60,
        "cache": 0.0375,
        "label": "Google Gemini 2.0 Flash",
    },
}

# Heurísticas do cenário "naive" (baseline sem Prompt-less).
# Naive = usar o LLM do jeito mais direto: colar docs brutos + system/tools
# longos + histórico no prompt. Não é um modo da pipeline — é o contraste
# da calculadora ("o que custaria sem compressão").
NAIVE_SYSTEM_TOKENS = 2500  # system prompt + persona + instruções longas
NAIVE_TOOLS_TOKENS = 1800  # tool defs verbosas
NAIVE_HISTORY_TOKENS = 3000  # histórico de conversa tipico
NAIVE_OVERHEAD = NAIVE_SYSTEM_TOKENS + NAIVE_TOOLS_TOKENS + NAIVE_HISTORY_TOKENS

# Pacote Prompt-less: system compacto + tools compactas (sem histórico)
PROMPTLESS_SYSTEM = 180  # prompts/system.compact.txt ~ típico
PROMPTLESS_TOOLS = 220  # tools.compact.yaml
PROMPTLESS_OVERHEAD = PROMPTLESS_SYSTEM + PROMPTLESS_TOOLS

DEFAULT_OUTPUT_TOKENS = 1200  # artefato gerado (historia/PRD/openapi)


def est_tokens(text: str) -> int:
    return max(0, len(text) // 4) if text else 0


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "pipeline.yaml").read_text(encoding="utf-8"))


def measure_inputs(tipo: str = "historia") -> dict[str, Any]:
    """Mede o cenário real a partir de inputs/."""
    cfg = load_cfg()
    budget = cfg.get("budget") or {}
    consolidated_chars = int(budget.get("consolidated_summary_max_tokens", 200)) * 4
    lines_per_chunk = int(budget.get("doc_lines_per_chunk", 40))
    chunk_summary_chars = int(budget.get("rag_chunk_max_tokens", 120)) * 2
    max_ctx = int(budget.get("max_context_tokens", 2000))

    raw = load_inputs(tipo)
    slim = preprocess(raw)
    state = _state_sem_gravar(
        {
            **slim,
            "status": "economia_measure",
            "previous_actions": ["ingest", "preprocess"],
        }
    )
    rag = compress_rag(
        slim,
        consolidated_chars=consolidated_chars,
        lines_per_chunk=lines_per_chunk,
        chunk_summary_chars=chunk_summary_chars,
    )
    template = ARTIFACT_TEMPLATES[tipo].read_text(encoding="utf-8")
    ctx = build_context(
        tipo=tipo,
        state=state,
        rag=rag,
        template=template,
        budget_tokens=max_ctx,
    )

    docs = raw.get("documents") or []
    docs_raw = sum(int(d.get("est_tokens_raw") or 0) for d in docs)
    docs_lines = sum(int(d.get("lines") or 0) for d in docs)
    figma_raw = est_tokens(json.dumps(raw.get("figma") or {}, ensure_ascii=False))
    regras_raw = est_tokens(yaml.dump(raw.get("regras") or {}, allow_unicode=True))
    eng_raw = est_tokens(yaml.dump(raw.get("engenharia") or {}, allow_unicode=True))
    template_tok = est_tokens(template)

    # Naive: joga tudo bruto + overhead típico de agente
    naive_payload = docs_raw + figma_raw + regras_raw + eng_raw + template_tok
    naive_input = naive_payload + NAIVE_OVERHEAD

    # Prompt-less: pacote montado (já inclui system.compact) + tools compactas
    promptless_input = int(ctx["est_tokens"]) + PROMPTLESS_TOOLS

    return {
        "fonte": "inputs/",
        "tipo": tipo,
        "docs": [
            {
                "name": d.get("name"),
                "lines": d.get("lines"),
                "est_tokens_raw": d.get("est_tokens_raw"),
            }
            for d in docs
        ],
        "docs_lines": docs_lines,
        "breakdown_raw": {
            "docs": docs_raw,
            "figma": figma_raw,
            "regras": regras_raw,
            "engenharia": eng_raw,
            "template": template_tok,
        },
        "rag": {
            "raw": rag.get("est_tokens_raw"),
            "compressed": rag.get("est_tokens_compressed"),
            "doc_reduction_pct": (rag.get("documents") or {}).get("reduction_pct"),
        },
        "naive_input_tokens": naive_input,
        "promptless_input_tokens": promptless_input,
        "package_est_tokens": ctx["est_tokens"],
    }


def measure_what_if(*, linhas: int, chars_por_linha: int = 80) -> dict[str, Any]:
    """Cenário hipotético: N linhas de doc + overheads típicos."""
    docs_raw = max(1, (linhas * chars_por_linha) // 4)
    # insumos estruturados típicos (figma+regras+eng+template)
    estruturados = 800
    naive_input = docs_raw + estruturados + NAIVE_OVERHEAD

    # Prompt-less: consolidado ~200 tok + state ~150 + template parcial ~200 + system/tools
    promptless_input = 200 + 150 + 200 + PROMPTLESS_OVERHEAD
    # teto do budget
    promptless_input = min(promptless_input, 2000)

    return {
        "fonte": "what-if",
        "tipo": "historia",
        "docs": [{"name": f"hipotetico_{linhas}linhas.txt", "lines": linhas, "est_tokens_raw": docs_raw}],
        "docs_lines": linhas,
        "breakdown_raw": {
            "docs": docs_raw,
            "figma": 300,
            "regras": 200,
            "engenharia": 150,
            "template": 150,
        },
        "rag": {
            "raw": docs_raw + estruturados,
            "compressed": 350,
            "doc_reduction_pct": round(100 * (1 - 200 / max(docs_raw, 1)), 1),
        },
        "naive_input_tokens": naive_input,
        "promptless_input_tokens": promptless_input,
        "package_est_tokens": promptless_input - PROMPTLESS_TOOLS,
    }


def custo_chamada(
    input_tokens: int,
    *,
    output_tokens: int,
    preco: dict[str, float],
    cache_hit: float = 0.0,
    cacheable_prefix: int = 0,
) -> dict[str, float]:
    """Custo de 1 chamada. cache_hit ∈ [0,1] sobre o prefixo cacheável."""
    cache_hit = max(0.0, min(1.0, cache_hit))
    prefix = min(cacheable_prefix, input_tokens)
    cached = int(prefix * cache_hit)
    uncached = input_tokens - cached

    usd_in = (uncached / 1_000_000) * preco["input"] + (cached / 1_000_000) * preco["cache"]
    usd_out = (output_tokens / 1_000_000) * preco["output"]
    return {
        "usd_input": round(usd_in, 6),
        "usd_output": round(usd_out, 6),
        "usd_total": round(usd_in + usd_out, 6),
        "tokens_cached": cached,
        "tokens_uncached": uncached,
    }


def calcular(
    medicao: dict[str, Any],
    *,
    modelo: str = "gpt-4o",
    runs_mes: int = 40,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    cache_hit: float = 0.5,
    artefatos_por_run: int = 2,  # historia + prd
) -> dict[str, Any]:
    if modelo not in MODELOS:
        raise SystemExit(f"modelo desconhecido: {modelo}. Opções: {', '.join(MODELOS)}")

    preco = MODELOS[modelo]
    naive_tok = int(medicao["naive_input_tokens"])
    pl_tok = int(medicao["promptless_input_tokens"])
    chamadas_mes = runs_mes * artefatos_por_run

    # Naive: pouco cache (system muda / histórico muda) → cache_hit baixo
    naive_c = custo_chamada(
        naive_tok,
        output_tokens=output_tokens,
        preco=preco,
        cache_hit=min(0.15, cache_hit),
        cacheable_prefix=NAIVE_SYSTEM_TOKENS + NAIVE_TOOLS_TOKENS,
    )
    # Prompt-less: system+tools estáveis → cache_hit alto no prefixo
    pl_c = custo_chamada(
        pl_tok,
        output_tokens=output_tokens,
        preco=preco,
        cache_hit=cache_hit,
        cacheable_prefix=PROMPTLESS_OVERHEAD,
    )

    tok_economizados = max(0, naive_tok - pl_tok)
    reducao_pct = round(100 * tok_economizados / max(naive_tok, 1), 1)

    usd_naive_mes = naive_c["usd_total"] * chamadas_mes
    usd_pl_mes = pl_c["usd_total"] * chamadas_mes
    usd_economia_mes = usd_naive_mes - usd_pl_mes
    usd_economia_ano = usd_economia_mes * 12

    return {
        "modelo": modelo,
        "modelo_label": preco["label"],
        "preco_usd_por_1m": {
            "input": preco["input"],
            "output": preco["output"],
            "cache": preco["cache"],
        },
        "hipoteses": {
            "runs_mes": runs_mes,
            "artefatos_por_run": artefatos_por_run,
            "chamadas_mes": chamadas_mes,
            "output_tokens_por_chamada": output_tokens,
            "cache_hit_promptless": cache_hit,
            "cache_hit_naive": min(0.15, cache_hit),
            "estimativa": "chars/4 (heurística; não é tokenizer oficial)",
        },
        "por_chamada": {
            "naive_input_tokens": naive_tok,
            "promptless_input_tokens": pl_tok,
            "tokens_economizados": tok_economizados,
            "reducao_pct": reducao_pct,
            "usd_naive": naive_c["usd_total"],
            "usd_promptless": pl_c["usd_total"],
            "usd_economia": round(naive_c["usd_total"] - pl_c["usd_total"], 6),
        },
        "mensal": {
            "usd_naive": round(usd_naive_mes, 4),
            "usd_promptless": round(usd_pl_mes, 4),
            "usd_economia": round(usd_economia_mes, 4),
            "tokens_naive": naive_tok * chamadas_mes,
            "tokens_promptless": pl_tok * chamadas_mes,
            "tokens_economizados": tok_economizados * chamadas_mes,
        },
        "anual": {
            "usd_economia": round(usd_economia_ano, 2),
            "usd_naive": round(usd_naive_mes * 12, 2),
            "usd_promptless": round(usd_pl_mes * 12, 2),
        },
        "medicao": medicao,
    }


def _fmt_usd(v: float) -> str:
    if abs(v) >= 1:
        return f"US$ {v:,.2f}"
    if abs(v) >= 0.01:
        return f"US$ {v:.4f}"
    return f"US$ {v:.6f}"


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def render_texto(rel: dict[str, Any]) -> str:
    m = rel["medicao"]
    p = rel["por_chamada"]
    mes = rel["mensal"]
    ano = rel["anual"]
    h = rel["hipoteses"]

    docs_resumo = ", ".join(
        f"{d['name']} ({d.get('lines')} linhas)" for d in (m.get("docs") or [])[:5]
    ) or "(nenhum doc)"

    linhas = [
        "╔══════════════════════════════════════════════════════════╗",
        "║         Prompt-less — Calculadora de economia            ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
        f"Modelo:     {rel['modelo_label']} ({rel['modelo']})",
        f"Fonte:      {m['fonte']} · artefato `{m['tipo']}`",
        f"Docs:       {docs_resumo}",
        f"Hipótese:   {h['runs_mes']} runs/mês × {h['artefatos_por_run']} artefatos "
        f"= {h['chamadas_mes']} chamadas/mês",
        f"Cache hit:  Prompt-less {h['cache_hit_promptless']:.0%} · "
        f"naive {h['cache_hit_naive']:.0%}",
        "",
        "── Por chamada (input tokens) ─────────────────────────────",
        f"  Sem Prompt-less (naive)   {_fmt_tok(p['naive_input_tokens']):>10} tokens",
        f"  Com Prompt-less           {_fmt_tok(p['promptless_input_tokens']):>10} tokens",
        f"  Economia                  {_fmt_tok(p['tokens_economizados']):>10}  "
        f"({p['reducao_pct']}%)",
        "",
        f"  Custo naive               {_fmt_usd(p['usd_naive'])}",
        f"  Custo Prompt-less         {_fmt_usd(p['usd_promptless'])}",
        f"  Economia / chamada        {_fmt_usd(p['usd_economia'])}",
        "",
        "── Projeção mensal ────────────────────────────────────────",
        f"  Tokens economizados       {_fmt_tok(mes['tokens_economizados'])}",
        f"  Custo naive               {_fmt_usd(mes['usd_naive'])}",
        f"  Custo Prompt-less         {_fmt_usd(mes['usd_promptless'])}",
        f"  Economia mensal           {_fmt_usd(mes['usd_economia'])}",
        "",
        "── Projeção anual ─────────────────────────────────────────",
        f"  Economia anual            {_fmt_usd(ano['usd_economia'])}",
        f"  (naive {_fmt_usd(ano['usd_naive'])} → prompt-less {_fmt_usd(ano['usd_promptless'])})",
        "",
        "── Breakdown do bruto (antes da compressão) ───────────────",
    ]
    for k, v in (m.get("breakdown_raw") or {}).items():
        linhas.append(f"  {k:<14} {_fmt_tok(int(v)):>10} tokens")

    rag = m.get("rag") or {}
    if rag.get("doc_reduction_pct") is not None:
        linhas += [
            "",
            f"  RAG docs: {_fmt_tok(int(rag.get('raw') or 0))} → "
            f"{_fmt_tok(int(rag.get('compressed') or 0))} "
            f"({rag['doc_reduction_pct']}% redução documental)",
        ]

    linhas += [
        "",
        "Notas: preços de referência (USD/1M tokens); estimativa chars÷4;",
        "naive = baseline sem Prompt-less (docs brutos + system/tools longos + histórico).",
        "Ajuste com --modelo, --runs-mes, --cache-hit, --output-tokens.",
    ]
    return "\n".join(linhas)


def comparar_modelos(medicao: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    rows = []
    for mid in MODELOS:
        rel = calcular(medicao, modelo=mid, **kwargs)
        rows.append(
            {
                "modelo": mid,
                "label": rel["modelo_label"],
                "reducao_pct": rel["por_chamada"]["reducao_pct"],
                "usd_mes": rel["mensal"]["usd_economia"],
                "usd_ano": rel["anual"]["usd_economia"],
            }
        )
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description="Calculadora de economia Prompt-less")
    p.add_argument("--tipo", default="historia", choices=["openapi", "mermaid", "historia", "prd"])
    p.add_argument("--modelo", default="gpt-4o", choices=list(MODELOS.keys()))
    p.add_argument("--runs-mes", type=int, default=40, help="quantas execuções/mês")
    p.add_argument(
        "--artefatos",
        type=int,
        default=2,
        help="artefatos LLM por run (default 2: historia+prd)",
    )
    p.add_argument("--output-tokens", type=int, default=DEFAULT_OUTPUT_TOKENS)
    p.add_argument(
        "--cache-hit",
        type=float,
        default=0.5,
        help="fração do prefixo estável lida do cache (0–1)",
    )
    p.add_argument("--what-if", action="store_true", help="cenário hipotético (não lê inputs/)")
    p.add_argument("--linhas", type=int, default=3000, help="linhas do doc no --what-if")
    p.add_argument("--comparar", action="store_true", help="tabela de economia por modelo")
    p.add_argument("--json", action="store_true", help="saída JSON")
    p.add_argument("--listar-modelos", action="store_true")
    args = p.parse_args()

    if args.listar_modelos:
        for mid, meta in MODELOS.items():
            print(
                f"{mid:<16} {meta['label']:<28} "
                f"in={meta['input']} out={meta['output']} cache={meta['cache']} $/1M"
            )
        return

    if args.what_if:
        medicao = measure_what_if(linhas=args.linhas)
    else:
        medicao = measure_inputs(args.tipo)

    kwargs = dict(
        runs_mes=args.runs_mes,
        output_tokens=args.output_tokens,
        cache_hit=args.cache_hit,
        artefatos_por_run=args.artefatos,
    )

    if args.comparar:
        rows = comparar_modelos(medicao, **kwargs)
        if args.json:
            print(json.dumps({"medicao": medicao, "comparativo": rows}, ensure_ascii=False, indent=2))
            return
        print(f"Economia mensal (runs={args.runs_mes}, artefatos={args.artefatos})")
        print(f"{'modelo':<16} {'redução':>8} {'US$/mês':>12} {'US$/ano':>12}")
        print("-" * 52)
        for r in rows:
            print(
                f"{r['modelo']:<16} {r['reducao_pct']:>7.1f}% "
                f"{r['usd_mes']:>12.4f} {r['usd_ano']:>12.2f}"
            )
        return

    rel = calcular(medicao, modelo=args.modelo, **kwargs)
    if args.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
    else:
        print(render_texto(rel))


if __name__ == "__main__":
    main()
