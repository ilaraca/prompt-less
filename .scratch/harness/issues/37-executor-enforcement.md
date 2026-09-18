# 37-executor-enforcement

**Kanban:** Feedback  

> Ajuste pós-reabertura 2026-09-18 entregue; aguarda review humana → Done.
**Blocked by:** 30, 31, 32, 33, 34  
**Prioridade:** P1.1

> Detalhe canônico: `.scratch/harness/board.md` § «37 — Limites efetivos do executor».
> Worktree: `.worktrees/37-executor-enforcement` · `feature/executor-enforcement`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> Base do pai na reabertura: `c2192db`.

## Aceite / ajustes

Ver board § 37 — checkboxes de ajuste e aceite marcados na entrega.

## Código

`src/executors/runner.py`, `devin.py`, `safe_exec.py`, `policy.py`. README + CHANGELOG.

## Implementation note

**HEAD:** `a6c8f76` · branch `feature/executor-enforcement`  
**Worktree:** `.worktrees/37-executor-enforcement`

### O que shipou (ajuste pós-reabertura)

- Contenção de writes dos **processos filhos**: sitecustomize FS-deny
  (`open` / `Path.write_*` / `os.open`) + `TMPDIR` dentro do repo; sandbox OS
  (`sandbox-exec` / `bwrap`) só quando a sonda verifica. Capacidade `writes`
  só é declarada se a contenção passar; senão `DispatchBlocked`.
- `EnforcedRunner` é **callable** (`runner(argv, profile=…)`) — contrato
  compartilhado com o adapter / ticket 35. `profile=None` = meta-CLI (pula
  allowlist do binário, mantém FS/rede/credenciais/tempo/recursos).
- `DevinAdapter._invoke_cli` **não** substitui mais `EnforcedRunner` por
  `run_argv`.
- README + CHANGELOG atualizados.

### Como verificar

```bash
cd .worktrees/37-executor-enforcement
PYTHONPATH=. python -m pytest tests/integration/test_executor_enforcement.py -q
```

Sem merge no pai / sem PR da filha — aguardando review humana → Done.
