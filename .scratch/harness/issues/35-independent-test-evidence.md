# 35-independent-test-evidence

**Kanban:** Feedback  
**Blocked by:** (ver board)  
**Prioridade:** P1.2

> Detalhe canônico: `.scratch/harness/board.md` § «35 — Testes e critérios de aceite independentes».
> Worktree: `.worktrees/35-independent-test-evidence` · `feature/independent-test-evidence`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> HEAD filha: `36bcbc3`.

## Aceite

Checkboxes no board § 35 — todos marcados na entrega.

## Código

`src/executors/devin.py`, `evidence.py`, `verify.py`. README + CHANGELOG
atualizados no mesmo commit da feature.

## Implementation note

- `_materialize_test_evidence` reexecuta sugestões do sidecar via runner do
  harness; `passed=True` do agente nunca vira `exit_code=0` sem execução.
  JSONL grava argv/stdout/stderr/exit + binding (`run_id`, repo, commits,
  `spec_hash`) e `executed_by=harness`.
- Verify exige harness + binding; códigos novos:
  `TEST_EVIDENCE_TAMPERED` / `TEST_EVIDENCE_BINDING` /
  `AC_WITHOUT_BEHAVIORAL_EVIDENCE`. `evidence_hashes.test_kinds` separa
  e2e / unit / stub_or_skip.
- HEAD: `36bcbc3` · `feature/independent-test-evidence` (sem push/PR da filha).
- Verificar:
  `PYTHONPATH=. python -m pytest tests/integration/test_independent_test_evidence.py tests/integration/test_evidence_verify.py -q`
  e no pai `PYTHONPATH=. python scripts/quality_gates.py` antes do merge.
- Parar em Feedback até revisão humana → Done.
