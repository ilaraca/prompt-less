# 14-apply-rollback

**Kanban:** Todo  
**Blocked by:** 21-auditable-approval (Done), 23-candidate-evals (Done)

> O `21` foi **Done** em 2026-09-18. Riscos residuais aceitos (não reabrir):
> `promote` grava `validations/promotion.json` e **não** aplica código; o
> binding é aos arquivos da run; o ledger HMAC não é JSONL append-only.
> Consumir `src.approval` / `assert_promotable` — `close_loop --approve`
> foi removido.
>
> O `23` foi **Done** em 2026-09-18 (pai `088d671`, PR #16). Residual
> aceito lá: `src.run` ainda lê `config/pipeline.yaml` do ROOT;
> `run_eval_suite` não passa o workspace ao `run`. Este ticket **executa**
> baseline e candidate sobre configs distintas (overlay ou
> `change.key/value` em arquivo versionado). Não tratar jitter de
> `avg_latency_ms` como melhoria comprovada. Rollback restaura bytes.

## Objetivo

Aplicar propostas `low` risk em config com backup; re-eval; rollback automático se regressão.

## Aceite

- [ ] apply de `change.key/value` em arquivos de config versionados
- [ ] snapshot pré-apply em `state/knowledge/snapshots/`
- [ ] re-roda eval suite; regressão → rollback + `rejected`
- [ ] risco `medium+` exige aprovação via `src.approval` (não `close_loop --approve`)
- [ ] testes: accept aplica; regressão reverte

## Implementation note

_(preencher ao mover para Feedback)_
