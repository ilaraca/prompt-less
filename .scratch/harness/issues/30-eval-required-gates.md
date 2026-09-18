# 30-eval-required-gates

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Aguardando review humana → Done.
**Blocked by:** —  
**Prioridade:** P0.1

> Detalhe canônico: `.scratch/harness/board.md` § «30 — Gates obrigatórios de avaliação».
> Worktree: `.worktrees/30-eval-required-gates` · `feature/eval-required-gates`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

Separar diagnóstico de aprovação em `score_case()`: dimensões obrigatórias
(spec, artefatos, rastreabilidade, pendências) não se compensam. Gate
`traceable` exige SourceRef válido; ID do claim sozinho não aprova.

## Aceite

- [x] Spec válida com qualquer artefato obrigatório ausente reprova.
- [x] Fonte inválida, rastreabilidade quebrada ou serviço incorreto reprova.
- [x] Uma dimensão obrigatória falsa nunca é compensada por outra.
- [x] Casos negativos entram na suíte e falham pelo motivo esperado.

## Código

`src/learning/evals.py` + testes de avaliação. README + CHANGELOG obrigatórios.

## Implementation note

**HEAD:** `3cf8149` · `feature/eval-required-gates`
(worktree `.worktrees/30-eval-required-gates`, rebaseada em `origin/main`
`221e032`). Sem push / sem PR da filha.

**O que shipou (ajuste)**
- Gate `traceable`: `_source_ref_valid` / `_claim_has_valid_sources` —
  `document` não vazio e `start_line` ≤ `end_line`.
- Regressões: claim sem fonte e fonte inválida com manifesto íntegro →
  `passed=False`, `fail_reasons` inclui `traceable`.
- README + CHANGELOG `[Unreleased]` atualizados.

**Como verificar**

```bash
cd .worktrees/30-eval-required-gates
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_eval_required_gates.py \
  tests/integration/test_eval_run_selection.py \
  tests/integration/test_candidate_evals.py \
  tests/integration/test_learning.py -q
# → 52 passed (focado required_gates: 11 passed)
```

**Residual:** `pip_audit` neste ambiente (Python 3.9 vs `build==1.6.1`).

**Pare.** Aguardando review humana → Done. Depois: merge no pai; liberar 35/37/39.
