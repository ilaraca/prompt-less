# 31-eval-run-selection

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.1

> Detalhe canônico: `.scratch/harness/board.md` § «31 — Seleção por execução».
> Worktree: `.worktrees/31-eval-run-selection` · `feature/eval-run-selection`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

Exigir `run_id` e carregar só artefatos do manifesto daquela run
(`_load_specs` / `_load_final_artifacts`), com checagem de integridade.
Espelhos de compatibilidade fora da seleção automática.

## Aceite

- [x] Uma execução antiga correta não faz a atual passar.
- [x] Runs simultâneas com entradas diferentes não misturam evidências.
- [x] Manifesto ausente, run divergente ou artefato adulterado reprova.
- [x] Run bloqueada pode ser avaliada como bloqueio esperado, mas seus
      artefatos não são liberados para implementação.

## Código

`src/learning/evals.py`, `src/runtime/run_store.py`. README + CHANGELOG.

## Implementation note

**HEAD:** `78c763a` (`feature/eval-run-selection`)

### O que shipou

- `select_run_evidence(root, run_id)` carrega só `integrity.files` de
  `runs/<run_id>/` (sha256 + cadeia HMAC via `verify_run_dir`).
- `_load_specs` / `_load_final_artifacts` deixam de usar `rglob`; espelho
  `outputs/` fora da seleção.
- `score_case` exige `run_id` quando há root em disco; `selection_ok` entra
  no gate; run `blocked` → `artifacts_released=false`.
- `RunStore.sealed_file_entries` / `resolve_sealed_path` / `verify_sealed_entry`.
- README + CHANGELOG atualizados.

### Como verificar

```bash
cd .worktrees/31-eval-run-selection
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_eval_run_selection.py \
  tests/integration/test_candidate_evals.py -q
# suíte integração: 314 passed, 1 skipped
# quality_gates: compile/lint/types/yaml ok; pip_audit falhou por Python 3.9
#   local (build==1.6.1 exige ≥3.10) — residual de ambiente, não do slice
```

### Residuais

- `pip_audit` no venv 3.9 local falha ao instalar `build==1.6.1` (lock ≥3.10);
  CI com matriz 3.10+ é a referência.
- Tickets 30/32 também editam `evals.py` — merge no pai pode precisar de
  rebase cuidadoso nas funções de score.
