# 36-repair-policy

**Kanban:** Feedback  
**Blocked by:** 30, 31, 32, 33, 34  
**Prioridade:** P1.2

> Detalhe canônico: `.scratch/harness/board.md` § «36 — Política completa no reparo».
> Worktree: `.worktrees/36-repair-policy` · `feature/repair-policy`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> Base do pai: `fef3f29` / board sync `435d1e3`.

## Aceite

Ver checkboxes no board § correspondente (marcados na entrega).

## Código

`src/executors/loop.py`, `policy.py` (reuso), `close_loop.py`. README + CHANGELOG.

## Implementation note

**HEAD:** `fb4f0bc` · branch `feature/repair-policy` · worktree
`.worktrees/36-repair-policy` (base `435d1e3`).

**O que shipou**

- `build_repair_request` reaplica profile da camada + `repo_root`
  (`resolve_repo_path` / realpath / symlink) a cada tentativa
- escapes (absoluto, `..`, symlink) e write negado → `denied_paths`
- `TEST_FAILED` só amplia `editable_surface` se autorizado; IDs RF/AC
  não são caminhos; `FILE_OUT_OF_SCOPE` só em `required_reverts`
- `attempt > max` → `exhausted` + `unresolved=true`
- `close_loop` passa profile/`--repo` e sempre re-verifica antes do repair
- README + CHANGELOG `[Unreleased]` atualizados

**Como verificar**

```bash
cd .worktrees/36-repair-policy
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. python3 -m pytest \
  tests/integration/test_repair_policy.py \
  tests/integration/test_executor_loop.py -q
```

18 passed.

**Residuais**

- `policy.py` não ganhou API nova — reusa `check_write_allowed` /
  `resolve_repo_path` existentes
- Sem push/PR da filha; merge no pai = humano

**Pare.** Aguardando review humana → Done.
