# 37-executor-enforcement

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** (ver board)  
**Prioridade:** P1.1

> Detalhe canônico: `.scratch/harness/board.md` § «37 — Limites efetivos do executor».
> Worktree: `.worktrees/37-executor-enforcement` · `feature/executor-enforcement`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> Base do pai: `fef3f29`.

## Aceite

Ver checkboxes no board § correspondente.

## Código

Ver board. README + CHANGELOG obrigatórios.

## Implementation note

**HEAD:** `e4d458b` · branch `feature/executor-enforcement`  
**Worktree:** `.worktrees/37-executor-enforcement`

### O que shipou

- `src/executors/runner.py` — `EnforcedRunner` aplica limits **durante** a
  execução (writes, comandos, scrub de credenciais, timeout, processos/memória
  best-effort, rede via sitecustomize + deny de CLIs); log JSONL com
  `"enforced": true`; `DispatchBlocked` se faltar capability.
- Profiles (`config/permission_profiles.yaml`) ganham `limits` +
  `required_capabilities`; `policy.normalize_limits` / `required_capabilities`.
- `DevinAdapter` exige `EnforcementContract` (default externo = sem garantias →
  bloqueia); grava `enforcement-contract.json` + sessão; CLI
  `--enforcement-contract` / `--allow-unenforced`.
- README + CHANGELOG atualizados (worktree/`shell=False` ≠ sandbox).

### Como verificar

```bash
cd .worktrees/37-executor-enforcement
PYTHONPATH=. python -m pytest tests/integration/test_executor_enforcement.py -q
```

Sem merge no pai / sem PR da filha — aguardando review humana → Done.
