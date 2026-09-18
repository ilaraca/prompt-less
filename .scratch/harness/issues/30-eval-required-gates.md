# 30-eval-required-gates

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Ajuste pós-reabertura
> integrado no pai. Não reabre worktree filha.
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
(worktree `.worktrees/30-eval-required-gates`). Integrado no pai
(`ae897b6` / `edd976b`). Sem push / sem PR da filha.

**O que shipou (ajuste)**
- Gate `traceable`: SourceRef com `document` não vazio e linhas válidas.
- Regressões: claim sem fonte / fonte inválida + manifesto íntegro →
  `passed=False`.
- README + CHANGELOG atualizados.

**Como verificar**

```bash
cd .worktrees/onda-merge
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_eval_required_gates.py -q
```
