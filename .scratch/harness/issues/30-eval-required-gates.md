# 30-eval-required-gates

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.1

> Detalhe canônico: `.scratch/harness/board.md` § «30 — Gates obrigatórios de avaliação».
> Worktree: `.worktrees/30-eval-required-gates` · `feature/eval-required-gates`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

Separar diagnóstico de aprovação em `score_case()`: dimensões obrigatórias
(spec, artefatos, rastreabilidade, pendências) não se compensam.

## Aceite

- [x] Spec válida com qualquer artefato obrigatório ausente reprova.
- [x] Fonte inválida, rastreabilidade quebrada ou serviço incorreto reprova.
- [x] Uma dimensão obrigatória falsa nunca é compensada por outra.
- [x] Casos negativos entram na suíte e falham pelo motivo esperado.

## Código

`src/learning/evals.py` + testes de avaliação. README + CHANGELOG obrigatórios.

## Implementation note

**HEAD:** `5ee18c366c3235a1c403e9afacc15ead4b0f1385` · `feature/eval-required-gates`
(worktree `.worktrees/30-eval-required-gates`). Sem push / sem PR da filha.

**O que shipou**
- `score_case()` agora expõe `required_gates` (AND) e `fail_reasons`;
  `layer_scores` permanece diagnóstico.
- Spec OK **não** compensa artefato ausente nem sinais faltando em
  história/PRD; rastreabilidade e pendências `blocking` entram no gate
  (não só em `critical`).
- Bloqueio esperado valida `expected_reason` /
  `expected_block_codes` (`ambiguous_status` atualizado).
- README + CHANGELOG `[Unreleased]` atualizados na worktree.

**Como verificar**

```bash
cd .worktrees/30-eval-required-gates
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_eval_required_gates.py \
  tests/integration/test_candidate_evals.py \
  tests/integration/test_learning.py -q
```

**Residual:** `scripts/quality_gates.py` — `audit` falhou neste ambiente
(Python 3.9 vs `build==1.6.1` no lock); compile/lint/types/yaml OK.
