# 08-ir-openapi-mermaid

**Kanban:** Done  
**Blocked by:** 04-spec-canonica (Done)

> Aprovado por humano em 2026-09-17. Branch `feature/ir-openapi-mermaid` publicada,
> rebaseada em `main` (já com o 18) e PR [#5](https://github.com/ilaraca/prompt-less/pull/5)
> aberto em `ilaraca/prompt-less`. Desbloqueia `29-operations-por-contexto` (direto) e,
> junto dos outros blockers, `15-hardening-deep` e `27-sdd-consumer`.

Aceite ampliado pela §5 do documento de propostas
(`pipeline/docs/propostas-melhoria-limites-atuais.md`, âncora `08-ir-openapi-mermaid`).

## Objetivo

Renderizar `openapi.yaml` e `sequence.mmd` deterministicamente a partir do Canonical Spec (mesma fonte que PRD/história).

É a base para que **todos** os artefatos derivados compartilhem a mesma autoridade
semântica: nenhum renderer pode inventar comportamento que não está no IR.

## Aceite

Escopo original do ticket:

- [x] `render_openapi(spec)` e `render_mermaid(spec)` em `src/renderers/`
- [x] `run openapi|mermaid` usa IR quando disponível (não só scaffold legado)
- [x] paths/status do OpenAPI alinhados a `operations`/`errors` do spec
- [x] testes: sem divergência IR ↔ OpenAPI ↔ Mermaid nos fixtures

Adicionado pela §5:

- [x] schemas de request/response representados no Canonical Spec
- [x] método, path e sucesso sem evidência ficam `unresolved` ou exigem revisão
- [x] validação estrutural do OpenAPI gerado
- [x] golden tests contra divergência entre IR (Canonical Spec), história, PRD, OpenAPI e Mermaid
- [x] nenhum renderer pode introduzir status, campo ou fluxo ausente no IR

## Métrica de sucesso

- zero divergência entre artefatos derivados nas golden fixtures;
- OpenAPI gerado passa validação estrutural;
- campo sem evidência nunca aparece como resolvido.

## Impacto no grafo

Blocker de `09-live-llm`, `15-hardening-deep` e `27-sdd-consumer`.

## Implementation note

Branch `feature/ir-openapi-mermaid` (worktree `.worktrees/08-ir-openapi-mermaid`),
base `701fe0b`. Nada foi enviado ao remoto.

### O que foi entregue

`openapi.yaml` e `sequence.mmd` passam a ser renderizados do Canonical Spec — a
mesma autoridade semântica da história e do PRD. Além dos renderizadores, o IR
ganhou schemas de request/response e marcação explícita de `unresolved`, e o
`run` ganhou um gate que **não emite** artefato derivado divergente do IR.

Decisões de projeto que mudam dado do IR:

- `Operation` ganhou `request_schema`, `response_schema` (`DataSchema` de
  `SchemaField` com `origin`/`requires_review` por campo) e `unresolved`.
- `success_status` passa a ser resolvido **somente** no caso inequívoco: uma
  única operação e um único 2xx declarado nas decisões (`ResolvedInt` com
  `origin: declared` e `source_claims`). Fora disso continua `value: null`,
  `requires_review: true` e entra em `unresolved`.
- `method`/`path` ausentes na UI entram em `unresolved` e abrem `OpenQuestion`
  **não bloqueante** (não param a pipeline, mas aparecem no PRD e no artefato).

### Arquivos alterados

| Arquivo | O que mudou |
|---|---|
| `src/domain/spec.py` | `SchemaField`, `DataSchema`, `ResolvedInt.source_claims`/`.resolved`, `Operation.{request_schema,response_schema,unresolved,resolved_success_status,from_raw}`, helpers `errors_of`/`http_statuses` |
| `src/preprocess.py` | inputs/columns do Figma carregam `type_origin` (`declared` vs `inferred`) |
| `src/spec/builder.py` | monta os schemas a partir da UI, resolve sucesso só com evidência, preenche `unresolved` e abre pergunta não bloqueante para method/path |
| `src/close_loop.py` | carrega operações via `Operation.from_raw` (round-trip do IR com schemas) |
| `src/renderers/openapi.py` (novo) | `render_openapi(spec, template=None)` + `build_openapi_document`, determinísticos |
| `src/renderers/mermaid.py` (novo) | `render_mermaid(spec, template=None)`, determinístico |
| `src/renderers/__init__.py` | reexporta os novos renderizadores; PRD lista ações com o status do IR ou `unresolved` |
| `src/validators/__init__.py` | `validate_openapi_document` (estrutural), `validate_openapi_against_spec` / `validate_mermaid_against_spec` (anti-divergência), `validate_derived_artifact`; `PipelineBlocked` ganhou `reason`/`report_path` |
| `src/run.py` | `openapi`/`mermaid` renderizam do IR; `_gate_derived` valida antes do emit, grava `validations/<tipo>-validation.json` e bloqueia a run |
| `tests/integration/test_derived_artifacts.py` (novo) | 14 testes: golden, determinismo, coerência entre os cinco artefatos, divergência injetada, unresolved e gate |
| `tests/fixtures/golden/openapi.yaml`, `sequence.mmd` (novos) | goldens byte-exatos de um IR estável (sem RAG) |
| `README.md`, `CHANGELOG.md` | seção "Artefatos derivados do IR", regras de tradução, limitações e entrada `Unreleased` (README+CHANGELOG atualizados conforme a regra do repo) |

### Comandos de verificação

```bash
cd .worktrees/08-ir-openapi-mermaid
.venv/bin/python -m pytest -q                      # 61 passed
PYTHONPYCACHEPREFIX=/tmp/pyc .venv/bin/python -m compileall -q src
.venv/bin/python -m src.run openapi --dry-run      # outputs/openapi.yaml derivado do IR
.venv/bin/python -m src.run mermaid --dry-run      # outputs/sequence.mmd derivado do IR
.venv/bin/python -m src.close_loop --spec runs/<id>/artifacts/canonical-spec.yaml \
  --result tests/fixtures/executor/execution_ok.json --out /tmp/verify   # round-trip do IR
```

### Resultado dos testes

- Antes: **47 passed** (baseline da branch).
- Depois: **61 passed** (47 preservados + 14 novos). Nenhum teste existente foi
  alterado.

### Evidência por critério de aceite

| Critério | Como foi atendido | Como verificar |
|---|---|---|
| `render_openapi` / `render_mermaid` em `src/renderers/` | módulos `openapi.py` e `mermaid.py`, assinatura `(spec, template=None)`, saída determinística | `test_golden_openapi`, `test_golden_mermaid`, `test_renderizadores_sao_deterministicos` |
| `run openapi\|mermaid` usa o IR | `_build_one` chama os renderizadores quando há Canonical Spec; scaffold legado só sem IR | `test_run_openapi_e_mermaid_usam_o_ir` (sem `DRY-RUN MARKERS`, com `x-operation-id`) |
| paths/status alinhados a `operations`/`errors` | path item e método vêm de `operations`; respostas `4xx` vêm de `errors` com `x-error-ids`/`x-source-claims` | `test_sem_divergencia_entre_ir_historia_prd_openapi_mermaid` (3 fixtures) |
| sem divergência IR ↔ OpenAPI ↔ Mermaid | validadores comparam status, path, operação, erro e campo com o IR | mesmo teste acima + `test_divergencia_injetada_e_detectada` |
| schemas de request/response no IR | `DataSchema`/`SchemaField` em `operations`, persistidos em `canonical-spec.yaml` | `grep -A20 request_schema runs/<id>/artifacts/canonical-spec.yaml` |
| method/path/sucesso sem evidência ficam `unresolved` | `Operation.unresolved`, `x-unresolved` na operação, `x-unresolved-operations` no documento, comentário `%%` no Mermaid, pergunta aberta | `test_unresolved_nunca_aparece_resolvido`, `test_sucesso_sem_evidencia_nao_vira_200`, `test_sucesso_com_evidencia_unica_e_resolvido` |
| validação estrutural do OpenAPI | `validate_openapi_document`: versão 3.x, `info`, path com `/`, operação com `operationId` e `responses`, chave de response válida, `$ref` resolvível, parâmetro de path declarado e obrigatório | `test_openapi_gerado_passa_validacao_estrutural` (happy_path, access_denied, two_services) |
| golden tests contra divergência entre os cinco artefatos | goldens byte-exatos dos dois novos artefatos + teste que roda `historia` (→ PRD), `openapi` e `mermaid` sobre o mesmo fixture, exige IR idêntico nas três runs e cruza RF/AC/erros/paths | `test_sem_divergencia_entre_ir_historia_prd_openapi_mermaid` |
| nenhum renderer introduz status/campo/fluxo fora do IR | gate `_gate_derived` bloqueia o emit (`reason: derived_artifact_divergence`) com códigos `ARTIFACT_STATUS_NOT_IN_IR`, `ARTIFACT_PATH_NOT_IN_IR`, `ARTIFACT_OPERATION_NOT_IN_IR`, `ARTIFACT_FIELD_NOT_IN_IR`, `ARTIFACT_ERROR_NOT_IN_IR`, `ARTIFACT_RESOLVED_WITHOUT_EVIDENCE`, `ARTIFACT_MISSING_UNRESOLVED_MARK` | `test_gate_bloqueia_artefato_divergente` (renderizador adulterado ⇒ nenhum `openapi.yaml` emitido) |

### Riscos e pontos para revisão humana

1. **Resolução do status de sucesso** — a regra "uma operação + um único 2xx nas
   decisões ⇒ `origin: declared`" é a única inferência nova. Nos fixtures
   `happy_path` e `access_denied` ela resolve `200`; em `two_services` fica
   `unresolved`. Se o time considerar que decisão de negócio não é evidência
   suficiente para o contrato, basta remover `unique_success` do builder e tudo
   volta a `unresolved` (os testes cobrem os dois lados).
2. **`unresolved` que sobra hoje** — `success_status` de `two_services` e de
   qualquer fixture com múltiplas ações; `method`/`path` sempre que a UI não
   declarar. Nesses casos o OpenAPI sai sem resposta de sucesso (só `4xx`), o
   que é intencional: melhor contrato incompleto que contrato inventado.
3. **`operations` não são fatiadas por serviço** — `_filter_regras_for_service`
   filtra apenas regras, então com `--all-contexts` cada contexto recebe todas
   as actions da UI (e os mesmos paths). Comportamento pré-existente, agora
   visível no OpenAPI por serviço. Fica registrado como limitação no README.
4. **Envelope de erro fora do IR** — `components.schemas.Error` (`code`,
   `message`, `details`) vem de `templates/openapi.skeleton.yaml`, não do
   Canonical Spec; é a única exceção permitida pelo validador
   (`ERROR_ENVELOPE_FIELDS`). Idem os atores FE/BFF/API do template Mermaid.
5. **Validação estrutural é própria, não `openapi-spec-validator`** — como
   pedido, nenhuma dependência nova foi instalada; a checagem usa PyYAML e cobre
   o subconjunto que a pipeline gera, não o schema OpenAPI completo. Se o time
   quiser conformidade total, é preciso aprovar uma dependência.
6. **Goldens são sensíveis por desenho** — `tests/fixtures/golden/*` fixam bytes
   dos renderizadores; mudança intencional exige regenerar os dois arquivos.
7. **Campos com tipo inferido** — colunas sem tipo no Figma entram com
   `origin: inferred`, `requires_review: true` e saem no OpenAPI com
   `x-type-origin: inferred`. Os evals contam `unexpected_inferences` só em
   `success_status`, então esses campos não entram no gate de evals — avaliar se
   deveriam.

Commits (após rebase em `main`): `848bc7e`, `f48408e`, `cebb96d`, `e75525c`.
Hashes anteriores ao rebase (`6d26235`..`cef45d8`) ficaram obsoletos.
Board **não** foi editado e nada foi marcado como `Done`.
