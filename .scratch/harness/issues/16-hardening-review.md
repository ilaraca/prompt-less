# 16-hardening-review

**Kanban:** Done  
**Blocked by:** — (hotfix pós-review de `docs/correcoes-engenharia-harness`)

## Objetivo

Endurecer gates de execução, provenance, evals semânticos e validação do Canonical Spec conforme review da main `a6cac20`.

## Aceite

- [x] policy de comandos sem bypass por `&&` / `;` / `||` (argv + sem shell)
- [x] verify fail-closed para layer/profile desconhecido
- [x] `FILE_OUT_OF_SCOPE` → `required_reverts`, não `editable_surface`
- [x] evals comparam `expected.yaml` (serviço, HTTP, sinais, bloqueio)
- [x] runs bloqueadas preservam claims/discarded no payload
- [x] traceability valida existência de claim IDs (+ órfãos warning)
- [x] defaults/inferências explícitos; status inválido não vira 422 silencioso
- [x] `confidence=0.0` preservado no builder e no loader
- [x] `NO_TESTS_REPORTED` é error em mudanças de código
- [x] learning: status `approved_for_experiment` (não `accepted`)
- [x] plano multi-repo marca `origin: heuristic` + `requires_review`
- [x] remover assert `or True` em test_runtime_isolation

## Implementation note

### O que shipou

Hotfix de hardening no repo `pipeline/` cobrindo os 12 itens de código do review (proteção de `main` no GitHub fica fora do código — ver abaixo).

1. **policy.py** — comandos parseados como argv (`shlex`); metacaracteres de shell negam; allow/deny por tokens (não prefixo de string); aceita `{executable, args}`.
2. **verify.py** — fail-closed (`UNKNOWN_EXECUTION_LAYER`); `NO_TESTS_REPORTED` = error em code change.
3. **loop.py** — `required_reverts` para `FILE_OUT_OF_SCOPE`; `editable_surface` só com paths in-scope (RF_* não entra).
4. **evals.py** — `score_case` compara `expected.yaml` (serviço, HTTP, sinais, ownership, blocked).
5. **run.py** + **PipelineBlocked** — claims/discarded preservados no payload bloqueado.
6. **validators** — `UNKNOWN_SOURCE_CLAIM`, ops/errors/claims duplicados, órfãos (warning), confidence em [0,1].
7. **builder** + **ResolvedInt** — `success_status` com origin/confidence/requires_review; status inválido abre pergunta (não default 422); confidence `0.0` preservado.
8. **accept.py** — status positivo = `approved_for_experiment`.
9. **plan.py** — `origin: heuristic`, `requires_review: true`.
10. **CI** — step `compileall` + validação YAML de profiles.

### Como verificar

```bash
cd pipeline
.venv/bin/pytest -v --tb=short
```

Esperado: **45 passed**.

Smoke manual útil:
- `check_command_allowed("./mvnw test && terraform apply", bff)` → False
- fixture `ambiguous_status` → `status=blocked` com `claims` não vazios no resultado
- repair de `execution_bad.json` → `required_reverts` contém `infra/prod/**`

### Fora deste ticket (governança GitHub)

Proteger `main` (required checks, PR obrigatório, sem force-push) exige settings no remote — não é alteração de código. CI já tem pytest + compileall; opcional: ruff/mypy/coverage depois.
