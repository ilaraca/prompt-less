# 12a-official-tokenizer

**Kanban:** Done  
**Blocked by:** 01-baseline-evals (Done), 02-runtime-execucao (Done) — **sem blocker aberto**

Desmembrado de `12-ci-tokenizer-redis` pela §5 do documento de propostas. **Não é infra:**
é biblioteca de tokenização, por isso não foi parqueado junto do `12b`.

## Comportamento entregue

Dado um provider/modelo, o budget e a telemetria usam o tokenizer correspondente, com
fallback explícito.

## Aceite

- [x] estratégia pluggable por provider
- [x] estimativa registra `method=official|heuristic`
- [x] diferença entre estimado e billable observada no modo live
- [x] budgets testados nos limites
- [x] fallback não é apresentado como contagem exata

## Por que não pode esperar demais

É pré-requisito honesto do `09-live-llm`: sem tokenizer oficial, budget e telemetria
seguem em `chars/4` heurístico e o custo de chamada paga fica invisível. Hoje há folga,
porque `09` ainda espera o `15` — este ticket já saiu da frente.

## Implementation note

Worktree `.worktrees/12a-official-tokenizer`, branch `feature/official-tokenizer`,
base `origin/main` (`648f062`). Sem push. README + CHANGELOG + `docs/rag-e-cli.md`
atualizados.

`src/tokenizer.py` com estratégias pluggable por provider (`openai` → tiktoken
`method=official`; `anthropic`/`google`/lib ausente → `method=heuristic` fail-open).
Budget (`context_builder`) e telemetria (`est_tokens_method`, `token_usage` no
resultado da run e no `llm_package.meta`) usam o tokenizer ativo. Hook
`observe_billable` persiste estimado vs billable para o `09-live`. Fallback nunca
é apresentado como contagem exata.

### Commits

| Hash | Mensagem |
|---|---|
| `3b7afcb` | feat: usa tokenizer oficial por provider com fallback heurístico |
| `1035df3` | test: cobre tokenizer oficial, fallback e budget nos limites |
| `cd73e72` | docs: documenta tokenizer por provider e fallback não-exato |

### Como verificar

```bash
cd .worktrees/12a-official-tokenizer
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
```

Esperado: **111 passed**. Conferir `est_tokens_method` / `token_usage.method` no JSON
da run e `hipoteses.estimativa_method` em `python -m src.economia --json`.

### Riscos residuais

- Anthropic/Gemini ainda não têm tokenizer local oficial.
- O encoding do tiktoken pode precisar de download na primeira run do CI.
- Recorte de consolidado ainda usa tokens×4 só como clip em caracteres; a
  telemetria é que usa o tokenizer.

**Fora de escopo (intencional):** Redis/`12b`, `--live`/`09`.

> Aprovado por humano em 2026-09-18. Riscos residuais aceitos (sem correção).
> Não reabre o worktree. O `09-live-llm` ficou sem blocker aberto (15 Done).
