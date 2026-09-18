# 39-case-regression-gates

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Aguardando review humana → Done.
**Blocked by:** 30, 31, 32  
**Prioridade:** P0.1 / P3

> Worktree: `.worktrees/39-case-regression-gates` · `feature/case-regression-gates`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier`

## Aceite

- [x] Caso aprovado → reprovado marcado mesmo com taxa igual.
- [x] Regressão crítica bloqueia; tolerância não crítica explícita/justificada.
- [x] Caso removido / conjunto incompatível impede comparação conclusiva.
- [x] Experimento registra referência, candidato, diff, condições e reservados.
- [x] Promoção exige benefício demonstrável (sem jitter de latência).
- [x] Avaliador/dados não são alterados pelo candidato.

## Implementation note

**HEAD:** `85b4f14` · `feature/case-regression-gates` · sem push/PR da filha.

**O que shipou (ajuste)**
- `apply_reserved_gate()`: hold-out com regressão/falha crítica →
  `decision=reject` / `critical_regression`, sem misturar métricas do dev.
- `improve_from_verify()` aplica o gate; experimento com `reserved_comparison`.
- README + CHANGELOG atualizados.

**Como verificar**

```bash
cd .worktrees/39-case-regression-gates
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_learning.py \
  tests/integration/test_candidate_evals.py -q
# → 35 passed
```

**Pare.** Aguardando Done → merge no pai (com 38).
