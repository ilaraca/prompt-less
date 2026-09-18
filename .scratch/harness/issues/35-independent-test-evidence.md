# 35-independent-test-evidence

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Worktree filha; sem push/PR.
**Blocked by:** (ver board)  
**Prioridade:** P1.2

> Detalhe canônico: `.scratch/harness/board.md` § «35 — Testes e critérios de aceite independentes».
> Worktree: `.worktrees/35-independent-test-evidence` · `feature/independent-test-evidence`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Aceite

Checkboxes no board § 35 — preenchidos na entrega do ajuste (pai sincroniza Kanban).

## Código

`src/executors/devin.py`, `evidence.py`, `runner.py`, `verify.py`. README + CHANGELOG
atualizados no mesmo commit.

## Implementation note

- `_materialize_test_evidence` reexecuta só runners de teste reconhecidos
  (`is_behavioral_test_command`); `git diff` / inspeção com `kind`/`covers` do
  sidecar não materializam `passed` nem vão ao JSONL como prova.
- Verify rejeita comando não-comportamental mesmo com `executed_by=harness` +
  exit 0 (`TEST_NOT_EVIDENCED`); AC só com locator →
  `AC_WITHOUT_BEHAVIORAL_EVIDENCE`.
- `EnforcedRunner.__call__` + `invoke_runner` unificam a interface com
  `run_argv`; teste de integração usa DevinAdapter + EnforcedRunner reais
  (wrapper `pytest` no PATH, sem stub na chamada de teste).
- README + CHANGELOG `[Unreleased]` atualizados.
- Verificar:
  `PYTHONPATH=. python -m pytest tests/integration/test_independent_test_evidence.py tests/integration/test_evidence_verify.py -q`
  e no pai `PYTHONPATH=. python scripts/quality_gates.py` antes do merge.
- Parar em Feedback até revisão humana → Done.
