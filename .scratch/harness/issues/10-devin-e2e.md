# 10-devin-e2e

**Kanban:** Todo  
**Blocked by:** 09-live-llm, 20-evidence-backed-verification (Done), 21-auditable-approval (Done)

## Objetivo

Integrar Devin CLI de verdade: handoff → execução → `ExecutionResult` → `close_loop`.

## Aceite

- [ ] `DevinAdapter` invoca CLI (ou API) e persiste resultado JSON
- [ ] `devin-from-promptless.sh` chama `close_loop` ao final
- [ ] traço em `runs/<id>/validations/verify-report.json`
- [ ] e2e opcional via `DEVIN_E2E=1` (skip no CI sem credencial)
- [ ] testes unitários do adapter com subprocess mock

Herdado do `20` e do `21` (riscos aceitos em 2026-09-18 — não reabrir
esses tickets). Continua **Todo** até o Done do `09`.

Do `21`:

- [ ] close_loop **não** usa `--approve`; aprovação humana é
      `python -m src.approval` (`request-approval` / `approve` / `promote`)
- [ ] promote do 21 é selo em `validations/promotion.json`; o binding é aos
      arquivos da run (spec, verify-report, `result_commit`), não a um
      segundo `git diff`

Do `20`:

- [ ] runner real grava o JSONL estruturado (`adapter-log.jsonl`); o verify
      do 20 já consome `--adapter-log` e recusa comando/teste só declarado
- [ ] worktree limpo vs `result_commit` antes do `close_loop`
      (`git status --porcelain` vazio, senão fail-closed)
- [ ] `base_commit` obrigatório antes da execução; `result_commit` ao concluir
- [ ] `ExecutionResult` gerado pelo adapter, não aceito só do agente
- [ ] workspace isolado; nenhuma alteração integrada sem verify aprovado

§5 âncora `10-devin-e2e` em `pipeline/docs/propostas-melhoria-limites-atuais.md`.

## Implementation note

_(preencher ao mover para Feedback)_
