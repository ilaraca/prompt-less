# 28-engineering-baseline-v2

**Kanban:** Done  
**Blocked by:** 22-code-evidence-spec (Done), 27-sdd-consumer (Done)

> Aprovado em 2026-09-18. Riscos residuais aceitos (não reabrir): sinais
> NFR por substring (`heuristic`); alertas/ADRs/bulkhead fora do catálogo
> v2; sem despacho a executor. Base `aaeb004` (PR #17 já na `main`).
> Fonte: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
> âncora `28-engineering-baseline-v2`.

O `22` já modela estado atual e gaps no IR. O `27` emite `sdd-package.yaml`
com tasks que citam NFR, mas **não** classifica NFR por tipo nem por
criticidade. Este ticket é quem seleciona o baseline. Não despacha executor
(`10` / `14`).

## Objetivo

Cada serviço recebe NFRs proporcionais ao seu tipo e criticidade sem inflar
o prompt.

## Aceite

- [x] `engenharia.yaml` versionado por schema
- [x] suporte a circuit breaker, metrics, tracing, idempotência e segurança
- [x] NFRs selecionados por contexto/camada, não enviados integralmente
- [x] cada NFR tem origem `baseline|declared|observed`
- [x] conflitos com o código atual geram gaps
- [x] templates antigos continuam compatíveis por migração
- [x] história, PRD e tasks SDD compartilham os mesmos IDs de NFR

## Métrica de sucesso

- NFRs críticos presentes nos serviços aplicáveis;
- aumento de contexto dentro do budget configurado;
- zero duplicação divergente entre história, PRD e tasks.

## Implementation note

Worktree **filha** `.worktrees/28-engineering-baseline-v2`, branch
`feature/engineering-baseline-v2`, base `origin/main` (`aaeb004`).
HEAD `5a2ddb2`. Sem remote próprio — esperado. Sem PR / push / merge no pai.

Shipou baseline de engenharia **v2**: schema versionado, catálogo com circuit
breaker / metrics / tracing / idempotência / segurança, seleção por camada +
criticidade, origem `baseline|declared|observed`, gaps `GAP-NFR-*` quando o
índice não mostra sinal, migração v1→v2 na ingest, IDs `NFR-*` compartilhados
entre história, PRD e tasks SDD (task recebe subconjunto da sua `layer`).
README + CHANGELOG `[Unreleased]` atualizados.

### Commit

| Hash | Mensagem |
|---|---|
| `5a2ddb2` | feat: baseline de engenharia v2 com NFRs selecionáveis por camada |

### Arquivos principais

- `src/engenharia.py` — catálogo, migração, `select_nfrs`, sinais/gaps
- `config/engenharia.schema.yaml` — contrato versionado
- `src/spec/builder.py` / `src/domain/spec.py` — NFRs no IR com origin/layers
- `src/renderers/__init__.py` / `src/renderers/sdd.py` — IDs alinhados; filtro por layer
- `inputs/engenharia.yaml` — exemplo v2
- `tests/integration/test_engineering_baseline_v2.py`
- `README.md` / `CHANGELOG.md`

### Como verificar

```bash
cd ".worktrees/28-engineering-baseline-v2"
PYTHONPATH=. python3.10 -m pytest tests/integration/test_engineering_baseline_v2.py -q
PYTHONPATH=. python3.10 -m pytest -q --cov=src --cov-fail-under=70
# esperado: 259 passed (suíte completa neste HEAD)
PYTHONPATH=. python -m src.run historia --dry-run --no-split
# → canonical-spec.yaml com nfrs[].origin; história/PRD com NFR-R-01…;
#    sdd-package tasks com nfr_ids por layer
```

Gates: compile/lint/mypy/yaml/secrets/tests/smoke OK em Python 3.10.
`pip_audit` falhou neste host (ensurepip aninhado / venv 3.9 legado) — não
é regressão do slice; CI 3.10+ continua a autoridade.

### Riscos residuais

1. **Sinais NFR no índice são substring** (`CircuitBreaker`, `MeterRegistry`,
   `OpenTelemetry`…). Falso positivo/negativo possível; gaps saem com
   `origin: heuristic`. Aperto futuro: AST/símbolos tipados.
2. **`pip_audit` local** depende de Python ≥3.10 e ensurepip funcional; o
   venv 3.9 do `pipeline/.venv` não instala `build==1.6.1` do lock.
3. **Alertas / ADRs / bulkhead** fora do catálogo v2 (próximo passo no README).
4. Não despacha executor (`10`/`14`).
