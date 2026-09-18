# 09-live-llm

**Kanban:** Done  
**Blocked by:** 08-ir-openapi-mermaid (Done), 15-hardening-deep (Done), 18-safe-run-storage (Done), 19-contextual-provenance (Done)

> Aprovado em 2026-09-18. Riscos residuais aceitos (não reabrir): Gemini
> sem client; loop de tools limitado; IDs Anthropic pinned; gate
> `derived_artifact`; `cost_usd` = tabela local.

## Objetivo

Ativar `--live` com clientes OpenAI Responses e Claude Messages consumindo `llm_package_*.json`, com telemetria de custo real.

## Aceite

- [x] implementação em `reason.py` (sem `NotImplementedError`)
- [x] env vars documentadas (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`)
- [x] métricas: tokens billable, cache hit quando disponível
- [x] dry-run permanece default; testes com HTTP mock
- [x] falha de API não corrompe `runs/<id>/`

## Implementation note

Worktree `.worktrees/09-live-llm`, branch `feature/live-llm`,
HEAD `af3e67b` (base `aaeb004`). Sem push / sem PR contra `main`.
README + CHANGELOG + `docs/rag-e-cli.md` atualizados.

`src/reason.py` passa a expor `live_generate` / `call_openai_responses` /
`call_claude_messages` (HTTP stdlib + transporte injetável). O estágio
`reason` em `handlers.py` chama a API **antes** de gravar pacote/artefato
live; dry-run continua default. Telemetria em `token_usage` /
`llm_package.meta.live`: `billable`, `delta`, `cache_hit` /
`cache_read_tokens`, `cost_usd` via `observe_billable` + `economia.MODELOS`.

### Como verificar

```bash
cd .worktrees/09-live-llm
PYTHONPATH=. .venv/bin/python scripts/quality_gates.py
# ou só os testes do slice:
PYTHONPATH=. .venv/bin/python -m pytest -q tests/integration/test_live_llm.py
```

Esperado: quality_gates OK; 262 passed na suíte completa. Com chave real:

```bash
export OPENAI_API_KEY=…   # ou ANTHROPIC_API_KEY + models.provider=anthropic
export PROMPTLESS_INTEGRITY_KEY=…
PYTHONPATH=. .venv/bin/python -m src.run openapi --live --no-split
```

### Riscos residuais

- Google Gemini ainda sem client `--live`.
- Loop de tools de recovery limitado a poucas rodadas; formato Responses
  de function_call pode precisar ajuste fino contra a API real.
- IDs de modelo Anthropic mapeados de nomes curtos (`claude-sonnet` →
  snapshot pinned); vendor pode renomear.
- Artefato live ainda passa pelo gate `derived_artifact` — saída fora do
  IR bloqueia a run (intencional).
- Preço `cost_usd` usa tabela local de referência, não a fatura do vendor.

**Fora de escopo (intencional):** `10-devin-e2e`, apply/rollback, Gemini.
