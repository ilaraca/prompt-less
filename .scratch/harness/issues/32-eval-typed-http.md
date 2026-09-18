# 32-eval-typed-http

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.1

> Detalhe canônico: `.scratch/harness/board.md` § «32 — Contratos HTTP tipados».
> Worktree: `.worktrees/32-eval-typed-http` · `feature/eval-typed-http`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

Comparar método, rota, serviço, `success_status` tipado e erros da operação.
Texto livre (RF/AC) não prova o contrato HTTP.

## Aceite

- [x] Status tipado incorreto reprova mesmo com número correto em outra seção.
- [x] Status correto em outro serviço/operação não compensa a divergência.
- [x] Sucesso ausente ou pendente não recebe valor presumido.
- [x] Fixtures declaram expectativas por operação e exercitam esses negativos.

## Código

`src/learning/evals.py`, fixtures, modelo canônico. README + CHANGELOG.

## Implementation note

**HEAD:** `59b7e87` · branch `feature/eval-typed-http` · worktree
`.worktrees/32-eval-typed-http` (base `a0010dc` / `origin/main`).

**O que shipou**

- `src/learning/evals.py` — `collect_operation_contracts` /
  `match_http_operations`; `collect_spec_statuses` só lê sucesso resolvido
  (`ResolvedInt`) + erros em `error_ids` (ignora RF/AC/perguntas)
- Fixtures default com `http_operations` (serviço, método, rota, sucesso,
  erros); `two_services` deixa de exigir 401 fantasma
- Testes negativos em `test_candidate_evals.py` (texto livre, outro serviço,
  sucesso pendente, órfão)
- README + CHANGELOG `[Unreleased]` atualizados

**Como verificar**

```bash
cd .worktrees/32-eval-typed-http
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. python -m pytest \
  tests/integration/test_candidate_evals.py \
  tests/integration/test_learning.py::test_eval_suite_smoke \
  tests/integration/test_baseline_pipeline.py -q
```

22 passed; suíte default `run_eval_suite` 6/6 (`http_status_match_rate=1.0`).

**Residuais**

- Fallback `http_statuses` (sem `http_operations`) ainda existe para fixtures
  antigas; o gate preferencial é por operação
- `_load_specs` ainda faz `rglob` (seleção por manifesto = ticket 31)
- Sem push/PR da filha; merge no pai = humano

**Pare.** Aguardando review humana → Done.
