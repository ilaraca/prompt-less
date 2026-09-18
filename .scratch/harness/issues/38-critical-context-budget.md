# 38-critical-context-budget

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** 35, 36, 37 (Done)  
**Prioridade:** P2.2

> Detalhe canônico: `.scratch/harness/board.md` § «38 — Contexto crítico e custo completo».
> Worktree: `.worktrees/38-critical-context-budget` · `feature/critical-context-budget`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> Base do pai: `f755cec`.

## Aceite

Ver checkboxes no board § correspondente.

## Código

Ver board. README + CHANGELOG obrigatórios.

## Implementation note

**HEAD:** `c1c9b11` · branch `feature/critical-context-budget`  
**Worktree:** `.worktrees/38-critical-context-budget`

### O que shipou

- `src/context_builder.py` — `_fit_to_budget` reserva RF/AC/contratos/evidências
  em `dynamic.critical`; omissões não-críticas com `reason` + `ref` recuperável;
  excesso do mínimo → `blocked` / `split_required` com `diagnosis` / `split_plan`.
- `src/runtime/handlers.py` — `context_build` passa Canonical Spec e levanta
  `PipelineBlocked` (`CRITICAL_BUDGET_*`); resultado inclui `budget_report` /
  `task_metrics`.
- `src/task_metrics.py` — `attempts`, duração, custo com `is_invoice=false`
  (`estimate` vs `observed_billing`).
- `close_loop` / `reason` — duração validação+reparo; live marca billing observado
  sem fatura falsa.
- `doc_compress` / `hybrid_retrieval` — omissões por budget com refs recuperáveis.
- Evals: dimensão `critical_context` no `layer_scores`; casos critical permanecem
  em `DEFAULT_CASES`.
- README + CHANGELOG atualizados.

### Como verificar

```bash
cd .worktrees/38-critical-context-budget
PYTHONPATH=. python3 -m pytest tests/integration/test_critical_context_budget.py tests/integration/test_tokenizer.py -q
```

### Residuais

- `split_required` diagnostica lotes e bloqueia — não reexecuta cada lote
  automaticamente; recuperação de omissões não-críticas via tools/re-RAG.
- Sem merge no pai / sem PR da filha — aguardando review humana → Done.
