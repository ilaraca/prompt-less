# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere a [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added

- **Aprovação auditável** (`21-auditable-approval`): CLI
  `python -m src.approval` com `request-approval`, `approve` e `promote`
  separados. O registro em `runs/<id>/validations/approval.json` guarda
  ator, timestamp, justificativa, origem e hashes de Canonical Spec,
  verify-report e `result_commit`, selados com `seal_hmac` (trilha HMAC
  do 19). Rejeição é persistida; promoção sem aprovação válida e
  vinculada falha fechado; mudar spec, diff ou commit expira a decisão;
  copiar o registro para outra run é recusado
- Testes (`tests/integration/test_auditable_approval.py`): promoção sem
  aprovação falha; alterar spec/diff/commit invalida; rejeição persiste;
  reuse cross-run recusado; HMAC adulterado é detectado
- **Verificação por evidência** (`20-evidence-backed-verification`): o
  `close_loop` deixa de confiar em `changed_files` / comandos / testes
  declarados no payload. `base_commit` e `result_commit` são obrigatórios;
  o verify confirma ancestralidade no mesmo repositório e calcula o diff
  com Git
- Policy avalia o diff real e o realpath (symlink em `src/` apontando para
  `infra/prod` é `FILE_OUT_OF_SCOPE` / `PATH_ESCAPES_REPO`)
- Comandos vêm do JSONL estruturado do adapter (`--adapter-log`); testes
  exigem comando, `exit_code`, timestamp ISO-8601 e artefato/log existente
- Rastreio RF/AC precisa existir no `result_commit` (arquivo e linha);
  divergência relato × evidência é `EVIDENCE_DIVERGENCE`
- `verify-report.json` inclui `evidence_hashes` (SHA-256 do diff, do log e
  dos artefatos; HMAC reusa `PROMPTLESS_INTEGRITY_KEY` / `seal_hmac` do 19)
- Testes (`tests/integration/test_evidence_verify.py`): payload forjado não
  esconde arquivo fora de escopo; teste só declarado é recusado; hashes
  reproduzíveis a partir do repo e dos logs
- **Storage seguro da run** (`18-safe-run-storage`): `src/runtime/atomic_io.py`
  com write-temp + `os.replace`, cópia atômica e contenção de caminho
  (`resolve_within`)
- `run_id` e id de serviço com formato canônico validado
  (`InvalidRunId` / `InvalidContextId`); `run_dir.resolve()` obrigado a ficar
  sob `<root>/runs` (`UnsafeRunPath`)
- `RunStore.bootstrap()` reserva o diretório com `mkdir` exclusivo: id repetido
  levanta `RunIdCollision` e preserva a run anterior; retomada via
  `bootstrap(resume=True)`
- Transições de status versionadas: `manifest.version` monotônica,
  `status_history`, `RunStateConflict` em escrita com versão obsoleta e
  `InvalidStatusTransition` em transição inválida
- Espelho em `outputs/` publicado por `.mirror-manifest.json` (run_id + sha256
  por arquivo), com remoção segura de artefatos obsoletos
- Testes adversariais (`tests/integration/test_safe_run_storage.py`): traversal,
  symlink, colisão de id, interrupção no commit da escrita e duas runs
  concorrentes
- **Proveniência contextual** (`19-contextual-provenance`): um identificador
  público `id` (`CLM-0001` / `CLM-R001` / `CLM-SYN-001`); chave multi-contexto
  `(context, id)`; `resolve_claim` fail-closed se o id for ambíguo
- Deduplicação de claims por identidade completa (`context`, texto, origin,
  `service_id`, `chunk_id`, sources); `id` público não é renomeado quando dois
  contextos repetem `CLM-0001`
- `ClaimLink` (método lexical + score) em RF/AC/erro; score < 0.6 marca
  `requires_review` e emite warning `LOW_CONFIDENCE_CLAIM_MATCH` sem mudar
  `status`
- `SourceRef.selected_lines` e `locator` (`$.bloqueios[0]`) para o trecho
  realmente usado; claims sintéticos ganham `content_hash` + seção
- Cadeia HMAC-SHA256 em `events.jsonl` com `kid` (`PROMPTLESS_INTEGRITY_KID`,
  anel `PROMPTLESS_INTEGRITY_KEYS` para rotação); selo depois de `finish`,
  `events_tip` = HMAC de `run_finished`
- Testes (`tests/integration/test_contextual_provenance.py`): multi-contexto
  sem perda, dedup por identidade, adulteração de evento/artefato e match
  de baixa confiança
- **OpenAPI e Mermaid derivados do IR** (`src/renderers/openapi.py`,
  `src/renderers/mermaid.py`): `run openapi|mermaid` passa a renderizar a partir
  do Canonical Spec — paths, métodos, schemas e status saem de
  `operations`/`errors`, não do scaffold legado
- **Schemas de request/response no Canonical Spec** (`DataSchema`/`SchemaField`):
  campos da UI viram schema rastreável, com `origin` e `requires_review` por
  campo (tipo inferido nunca aparece como declarado)
- **Gate de artefato derivado** (`validate_derived_artifact`): validação
  estrutural do OpenAPI gerado (versão, paths, responses, `$ref`, parâmetros de
  path) mais checagem anti-divergência contra o IR; divergência bloqueia o emit
  (`reason: derived_artifact_divergence`) e grava
  `validations/<tipo>-validation.json`
- **Golden tests** (`tests/integration/test_derived_artifacts.py`,
  `tests/fixtures/golden/`): falham se IR, história, PRD, OpenAPI e Mermaid
  divergirem, e se um status/campo/path inventado escapar

### Changed

- `close_loop --approve` deixa de marcar `execution.approved = True`.
  O atalho foi removido: use `python -m src.approval`. `approved=False`
  no payload ainda gera `needs_approval` no verify; promoção exige o
  registro auditável
- `close_loop` / `verify_execution` exigem checkout Git (`--repo`) e log
  estruturado do adapter; `changed_files` e `commands_executed` do payload
  só servem para detectar divergência, não como evidência
- `manifest.json`, `state.json`, `provenance.json`, `latest.json`,
  `canonical-spec.yaml`, `spec-validation.json` e `llm_package_*.json` passam a
  ser gravados atomicamente
- Contrato único de contexto: o que é por serviço fica em `contextos/<id>/` na
  run (`artifacts/`, `validations/`) e no espelho; o diretório morto
  `runs/<id>/contexts/` deixa de ser criado
- `EventStore` não cria mais o arquivo no construtor (o diretório da run só
  nasce no `bootstrap`); cada evento carrega `prev_hash`/`hash`
- `emit` grava artefatos com write-temp + `os.replace` (digest precisa do
  arquivo já commitado)
- História/PRD passam a listar os claims utilizados na seção Proveniência
- `provenance.json` agrega `spec.claims` (inclui sintéticos `CLM-*-SYN-*`)
- `Operation` do IR ganha `request_schema`, `response_schema` e `unresolved`;
  `success_status` só é resolvido com evidência (um único 2xx declarado nas
  decisões e uma única operação) e agora carrega `source_claims`
- Método/path ausentes na UI ficam `unresolved`, viram pergunta aberta não
  bloqueante e aparecem como `x-unresolved-operations` no OpenAPI
- PRD lista ações com o status de sucesso do IR ou `unresolved` explícito

### Planejado (série 2)

- Modo `--live` (OpenAI / Claude)
- Devin CLI real no `close_loop`
- Orquestração declarativa via `pipeline.yaml` (stages)
- Tokenizer oficial + Redis opcional
- Execução concorrente por ondas
- Apply de propostas + rollback
- Hardening profundo (debugger, injection, recovery, golden recall)

## [0.2.0] - 2026-09-12

Engineering Harness (série 1 + hotfixes 16–17): runtime isolado, provenance,
Canonical Spec, ciclo executor, plano multi-repo, autoaperfeiçoamento, CI e
gates endurecidos.

### Added

- **Runtime por `run_id`** (`src/runtime/`): `runs/<id>/` com `manifest.json`,
  `events.jsonl`, `artifacts/`, `contexts/`, `validations/` e espelho em `outputs/`
- **Provenance e claims** (`src/domain/claim.py`, `source_ref.py`, `chunk.py`):
  claims com `SourceRef` obrigatório; `validations/provenance.json` por run
- **Canonical Spec v1** (`src/domain/spec.py`, `src/spec/builder.py`): IR
  verificável (`canonical-spec.yaml`) + quality gate (`src/validators/`)
- **Renderizadores** (`src/renderers/`): história/PRD alinhados ao IR
- **Ciclo executor** (`src/close_loop.py`, `src/executors/`): verify contra spec
  e policy de camada, aprovação e reparo limitado; adapter Devin (stub)
- **Policy de camada** (`config/permission_profiles.yaml`, `policy.py`): allow/deny
  de escrita e comandos por profile (`bff` / `api` / `mfe` / …)
- **Plano multi-repo** (`src/plan_repos.py`, `src/planning/`): grafo, camadas e
  `implementation_plan.yaml|json` a partir de `mapa-servicos.yaml`
- **Autoaperfeiçoamento controlado** (`src/improve.py`, `src/learning/`):
  diagnose → propostas (playbook) → eval suite → gate
  `approved_for_experiment` (sem apply automático)
- **Baseline de evals** (`tests/fixtures/`, `learning/evals.py`): casos
  happy/access_denied/ambiguous/two_services com scoring por camada
- **CI** (`.github/workflows/ci.yml`): `compileall`, validação YAML de profiles,
  pytest, smoke `plan_repos`
- CLIs: `python -m src.close_loop`, `python -m src.plan_repos`,
  `python -m src.improve`
- Configs: `permission_profiles.yaml`, `playbook.yaml`, `failure-patterns.yaml`

### Changed

- Pipeline `src.run` passa a emitir Canonical Spec + validação antes do emit;
  runs bloqueadas preservam `claims` / `discarded` no payload
- Status de aceite de propostas: `approved_for_experiment` (não `accepted`)
- Plano multi-repo marca `origin: heuristic` e `requires_review: true`
- Evals comparam `expected.yaml` (serviço, HTTP, sinais, ownership, blocked)
  e pontuam por camada (`ingestion` / `canonical_spec` / `artifacts` / `provenance`)

### Fixed

- Policy: comandos como argv (`shlex`); metacaracteres de shell negam;
  allow/deny por tokens (não prefixo de string)
- Policy: `normalize_repo_path` rejeita absoluto, drive e `..` (path traversal)
- Verify fail-closed para layer/profile desconhecido; `NO_TESTS_REPORTED` é
  error em mudanças de código
- `FILE_OUT_OF_SCOPE` → `required_reverts` (não `editable_surface`)
- Traceability: `UNKNOWN_SOURCE_CLAIM`, `CLAIM_WITHOUT_SOURCE`,
  `CLAIM_SOURCE_INVALID`; órfãos em warning
- Defaults/inferências explícitos; status HTTP inválido não vira 422 silencioso;
  `confidence=0.0` preservado; `unexpected_inferences` calculado
- Removido `nfr_ids` morto e assert `or True` em teste de runtime

## [0.1.0] - 2026-09-10

Pipeline Prompt-less de artefatos com compressão de contexto (pré-harness).

### Added

- Ingest / preprocess / state / RAG estrutural / context build / reason / emit
- Artefatos: OpenAPI, Mermaid, história (BDD + NFR) e PRD (handoff SDD)
- Microsserviços: `mapa-servicos.yaml`, `--context` / `--all-contexts`,
  `scan-repos.sh`, `marcar.py` (IDF), `repo_index.py`
- Calculadora de economia (`src/economia.py`) vs baseline naive
- Script `devin-from-promptless.sh` e guia `docs/rag-e-cli.md`
- Baseline NFR de documentação (README, CHANGELOG, docs de API por linguagem)

[Unreleased]: https://github.com/ilaraca/prompt-less/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ilaraca/prompt-less/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ilaraca/prompt-less/releases/tag/v0.1.0
