# 38-critical-context-budget

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Aguardando review humana → Done.
**Blocked by:** 35, 36, 37  
**Prioridade:** P2.2

> Worktree: `.worktrees/38-critical-context-budget` · `feature/critical-context-budget`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier`

## Aceite

- [x] Conteúdo crítico não desaparece silenciosamente ao reduzir orçamento.
- [x] Excesso do mínimo crítico gera divisão ou bloqueio com diagnóstico.
- [x] Omissões têm motivo e referência recuperável.
- [x] Cobertura crítica permanece no conjunto de avaliação.
- [x] Métricas da tarefa incluem tentativas e não apresentam estimativa como fatura.

## Implementation note

**HEAD:** `e96bc94` · `feature/critical-context-budget` · sem push/PR da filha.

**O que shipou (ajuste)**
- Gate `critical_coverage_ok`: `silent_critical_loss` / cobertura incompleta
  sem block/split explícito → `passed=False` + `fail_reasons`.
- Regressões em `test_critical_context_budget.py`.
- README + CHANGELOG `[Unreleased]`.

**Como verificar**

```bash
cd .worktrees/38-critical-context-budget
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_critical_context_budget.py -q
# → 13 passed
```

**Pare.** Aguardando Done → merge no pai (com 39).
