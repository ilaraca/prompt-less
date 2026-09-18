# 14-apply-rollback

**Kanban:** Done  
**Blocked by:** 21-auditable-approval (Done), 23-candidate-evals (Done)

> Aprovado em 2026-09-18. Riscos residuais aceitos (não reabrir): overlay
> sem consumidor completo de negócio no IR; jitter de latência não prova
> melhoria; `promote` só selo; suíte default cara sem `--cases`.

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

- [x] apply de `change.key/value` em arquivos de config versionados
- [x] snapshot pré-apply em `state/knowledge/snapshots/`
- [x] re-roda eval suite; regressão → rollback + `rejected`
- [x] risco `medium+` exige aprovação via `src.approval` (não `close_loop --approve`)
- [x] testes: accept aplica; regressão reverte

## Implementation note

**Sha:** `f9f2950` (`feature/apply-rollback`, worktree
`.worktrees/14-apply-rollback`). Base `aaeb004`. Sem push / sem PR.

**O que entrou**

- CLI `python -m src.apply --proposal-json …` +
  `src/learning/apply_rollback.py`: snapshot de bytes → aplica
  `change.key/value` (YAML nomeado ou `config/proposal-overlay.yaml`) →
  re-eval → regressão restaura bytes e marca `rejected`
- `src/runtime/config_load.py`: `run` / `run_eval_suite` mesclam o overlay
  no `pipeline.yaml` (baseline × candidate com cfg distinto)
- Risco `medium+` → `assert_promotable` (`--run-dir` + `--run-id`)
- README + CHANGELOG `[Unreleased]`; testes em
  `tests/integration/test_apply_rollback.py`

**Como verificar**

```bash
cd .worktrees/14-apply-rollback
PYTHONPATH=. .venv/bin/python scripts/quality_gates.py
# ou fatiado:
PYTHONPATH=. .venv/bin/python -m pytest -q tests/integration/test_apply_rollback.py
```

Demo mínima (com proposta `low` e `--cases happy_path`):

```bash
PYTHONPATH=. .venv/bin/python -m src.apply --root /tmp/pl-demo \
  --proposal-json /tmp/prop.json --cases happy_path
```

**Residuais (não reabrir neste slice)**

- Overlay/keys ainda não têm consumidor completo no IR; o apply garante
  persistência versionada + gate anti-regressão, não efeito de negócio
  por chave
- Gate de produção é anti-regressão; jitter de `avg_latency_ms` sozinho
  não prova melhoria (não entra como critério de keep)
- `promote` continua só selo — apply de config é este comando, não o `21`
- Suíte default de apply é a completa se `--cases` omitido (custo alto)

README + CHANGELOG atualizados neste commit.
