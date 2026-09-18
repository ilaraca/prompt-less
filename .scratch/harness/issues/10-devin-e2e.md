# 10-devin-e2e

**Kanban:** Done  
**Blocked by:** 09-live-llm (Done), 20-evidence-backed-verification (Done), 21-auditable-approval (Done)

> Aprovado em 2026-09-18. Riscos residuais aceitos (não reabrir): sidecar
> necessário para testes/build no JSONL; `DEVIN_E2E` só com CLI autenticado;
> auto-commit local sem push/PR. `12b`/`13` fora deste slice.

## Objetivo

Integrar Devin CLI de verdade: handoff → execução → `ExecutionResult` → `close_loop`.

## Aceite

- [x] `DevinAdapter` invoca CLI (ou API) e persiste resultado JSON
- [x] `devin-from-promptless.sh` chama `close_loop` ao final
- [x] traço em `runs/<id>/validations/verify-report.json`
- [x] e2e opcional via `DEVIN_E2E=1` (skip no CI sem credencial)
- [x] testes unitários do adapter com subprocess mock

Herdado do `20` e do `21` (riscos aceitos em 2026-09-18 — não reabrir
esses tickets). Liberado pelo Done do `09`.

Do `21`:

- [x] close_loop **não** usa `--approve`; aprovação humana é
      `python -m src.approval` (`request-approval` / `approve` / `promote`)
- [x] promote do 21 é selo em `validations/promotion.json`; o binding é aos
      arquivos da run (spec, verify-report, `result_commit`), não a um
      segundo `git diff`

Do `20`:

- [x] runner real grava o JSONL estruturado (`adapter-log.jsonl`); o verify
      do 20 já consome `--adapter-log` e recusa comando/teste só declarado
- [x] worktree limpo vs `result_commit` antes do `close_loop`
      (`git status --porcelain` vazio, senão fail-closed)
- [x] `base_commit` obrigatório antes da execução; `result_commit` ao concluir
- [x] `ExecutionResult` gerado pelo adapter, não aceito só do agente
- [x] workspace isolado; nenhuma alteração integrada sem verify aprovado

§5 âncora `10-devin-e2e` em `pipeline/docs/propostas-melhoria-limites-atuais.md`.

## Implementation note

Worktree `.worktrees/10-devin-e2e`, branch `feature/devin-e2e`,
HEAD `dca477f` (base `cbbad02`). Sem push / sem PR contra `main`.
README + CHANGELOG atualizados.

`DevinAdapter.execute` invoca `devin --print --prompt-file …` (runner
injetável nos testes), grava `devin-session.json` (metadados) +
`adapter-log.jsonl` (só comandos de build/teste do sidecar), faz commit
automático do resultado e monta `execution.json` a partir do Git.
`scripts/devin-from-promptless.sh` chama `python -m src.executors.devin
--close-loop`. Verify exige worktree limpo (`DIRTY_WORKTREE`).
Aprovação humana: `src.approval` (sem `close_loop --approve`).

### Como verificar

```bash
cd .worktrees/10-devin-e2e
PYTHONPATH=. .venv/bin/python scripts/quality_gates.py
# ou só o slice:
PYTHONPATH=. .venv/bin/python -m pytest -q tests/integration/test_devin_adapter.py
```

Esperado: quality_gates OK; 293 passed + 1 skipped (`DEVIN_E2E`). Com CLI:

```bash
./scripts/devin-from-promptless.sh /caminho/app \
  --spec outputs/canonical-spec.yaml --layer bff --run-id <id>
# → runs/<id>/validations/verify-report.json
# depois: python -m src.approval request-approval|approve|promote
```

### Riscos residuais

- Comandos internos da sessão Devin não são espelhados automaticamente no
  JSONL — testes/build precisam do sidecar
  `docs/prompt-less/execution-result.json` (ou log materializado); sem isso
  code change falha fechado.
- `DEVIN_E2E=1` depende de CLI autenticado e rede; CI sem credencial skipa.
- Auto-commit do adapter cria um commit local no checkout isolado; não faz
  push nem abre PR.
- `12b` (Redis) e `13` (paralelo) fora de escopo — não iniciados.

**Fora de escopo (intencional):** `12b-state-backend-redis`, `13-parallel-exec`.
