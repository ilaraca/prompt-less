# 09-live-llm

**Kanban:** Todo  
**Blocked by:** 08-ir-openapi-mermaid (Done), 15-hardening-deep (Done), 18-safe-run-storage (Done), 19-contextual-provenance (Done) — **sem blocker aberto, pode iniciar**

> Liberado em 2026-09-18 pelo Done do `15`. Worktree filha nova; base o pai
> / `origin/main` (`e9bdd91`), **não** a worktree antiga do 15. `12a` já é
> Done. Rebloqueio §5 cumprido.

## Objetivo

Ativar `--live` com clientes OpenAI Responses e Claude Messages consumindo `llm_package_*.json`, com telemetria de custo real.

## Aceite

- [ ] implementação em `reason.py` (sem `NotImplementedError`)
- [ ] env vars documentadas (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`)
- [ ] métricas: tokens billable, cache hit quando disponível
- [ ] dry-run permanece default; testes com HTTP mock
- [ ] falha de API não corrompe `runs/<id>/`

## Implementation note

_(preencher ao mover para Feedback)_
