# 35-independent-test-evidence

**Kanban:** Feedback  
**Blocked by:** (ver board)  
**Prioridade:** P1.2

> Detalhe canônico: `.scratch/harness/board.md` § «35 — Testes e critérios de aceite independentes».
> Worktree: `.worktrees/35-independent-test-evidence` · `feature/independent-test-evidence`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> HEAD filha: `36bcbc3`.

## Aceite

Ver checkboxes no board § correspondente (marcados na entrega).

## Código

`src/executors/devin.py`, `evidence.py`, `verify.py`. README + CHANGELOG
atualizados.

## Implementation note

- Sidecar só sugere; harness reexecuta e captura exit/argv/logs + binding.
- `passed=True` sozinho nunca basta; AC exige prova comportamental.
- Verificar: pytest `test_independent_test_evidence.py` +
  `scripts/quality_gates.py` no pai antes do merge.
- Parar em Feedback até revisão humana → Done.
