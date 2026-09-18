# 34-cli-failure-exit

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.3

> Detalhe canônico: `.scratch/harness/board.md` § «34 — Falha inequívoca na CLI».
> Worktree: `.worktrees/34-cli-failure-exit` · `feature/cli-failure-exit`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

Propagar `blocked`/`failed` como exit code ≠ 0 em `src.run.main()`, com
JSON/diagnóstico legível. Bloqueio impede despacho ao executor.

## Aceite

- [x] Teste de subprocesso real confirma exit code não zero em blocked/failed.
- [x] Sucesso válido mantém exit code zero.
- [x] Bloqueio impede despacho ao executor e reutilização de história antiga.
- [x] Automação recebe estado e motivo coerentes com o manifesto.

## Código

`src/run.py` e consumidores. README + CHANGELOG.

## Implementation note

**HEAD:** `addea9a` · branch `feature/cli-failure-exit` · worktree
`.worktrees/34-cli-failure-exit` (base `a0010dc` / `origin/main`).

**O que shipou**

- `src/run.py` — `main()` imprime JSON e sai com **exit 2** em
  `blocked`/`failed`; exceções viram JSON `{status, error, error_type}`;
  flags `--inputs-dir` / `--output-root`
- `RunStore.invalidate_mirror` — em blocked/failed poda o espelho anterior e
  grava `.mirror-manifest.json` com `status` + `reason`; `result_summary.reason`
  no manifesto alinha com o JSON da CLI
- `src/runtime/consume.py` — `assert_run_ready_for_executor` (identidade +
  estado); gate em `python -m src.executors.devin --root … --run-id …`
- README + CHANGELOG `[Unreleased]` atualizados

**Como verificar**

```bash
cd .worktrees/34-cli-failure-exit
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. python -m pytest tests/integration/test_cli_failure_exit.py -q
```

6 passed (subprocess blocked/failed/success + gate Devin + espelho).

**Residuais**

- Arquivos nunca listados num `.mirror-manifest.json` (colocados à mão em
  `outputs/`) continuam fora do prune — o gate de consumo + exit code cobrem
  o caminho de automação
- `evals.py` intocado (escopo do ticket)
- Sem push/PR da filha; merge no pai = humano

**Pare.** Aguardando review humana → Done.
