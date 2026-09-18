# 13-parallel-exec

**Kanban:** Done  
**Blocked by:** 10-devin-e2e (**Done**), 12b-state-backend-redis (⏸ — **não bloquear**), 18-safe-run-storage (Done), 24-evidence-based-planning (Done)

> Worktree filha `.worktrees/13-parallel-exec`, branch
> `feature/parallel-exec`, base `origin/main` (`52e3651`, pós PR #19).
> `12b` parqueado — CAS/lock no **file backend**, sem Redis.
> Não reabrir a filha do 10.

## Objetivo

Executar adapters por **onda** do `implementation_plan` com limite de paralelismo e relatório agregado.

## Aceite

- [x] scheduler consome `waves` do plano
- [x] N execuções concorrentes com semáforo configurável
- [x] agregação de `ExecutionResult` + verify por repo
- [x] falha numa task não apaga resultados das irmãs da onda
- [x] testes com adapter fake paralelo
- [x] state file backend com compare-and-set / lock (sem Redis/`12b`)

## Implementation note

**HEAD:** `04455e2` · branch `feature/parallel-exec` · worktree
`.worktrees/13-parallel-exec` (base `52e3651` / `origin/main`).

**O que shipou**

- `src/executors/scheduler.py` — `run_plan_waves` consome `waves` do
  `implementation_plan`, semáforo `max_concurrency`, agrega
  `ExecutionResult` + verify por repo; falha isolada não apaga irmãs
- CLI `python -m src.parallel_exec` (`--dry-run` / `--stub` /
  `--max-concurrency` / `--state` / `--out`)
- `src/state_store.py` — `FileStateBackend` + `compare_and_set_state` +
  `file_lock` (fcntl); Redis continua rejeitado (`12b` parqueado)
- README + CHANGELOG `[Unreleased]` atualizados (execução paralela deixa
  de ser “ainda não roda”)

**Como verificar**

```bash
cd .worktrees/13-parallel-exec
PYTHONPATH=. python scripts/quality_gates.py
# ou só o slice:
PYTHONPATH=. python -m pytest tests/integration/test_parallel_exec.py -q
PYTHONPATH=. python -m src.parallel_exec --plan runs/plan/implementation_plan.json --dry-run
```

Gates locais: compile/lint/mypy/yaml/secrets/audit/tests/smoke OK
(303 passed + 1 skipped; coverage ~80%). Sem mypy overrides novos.

**Residuais**

- CLI sem wiring Devin-por-task: usa `--stub` ou `adapter=` injetado em
  `run_plan_waves`; handoff Devin real continua via `10`
- Onda seguinte ainda roda mesmo se a anterior teve falha parcial
  (não há aborto de plano — só isolamento por task)
- Redis / retomada multi-worker: fora de escopo (`12b`)

**Pare.** Não tocar em `12b` nem `board.md`. Merge no pai = humano.
