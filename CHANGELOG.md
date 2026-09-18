# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere a [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Fixed

- `pip-audit --strict` na matriz 3.10–3.13 deixava de passar: o lock compilado
  em 3.9 pinava `pip` 26.0.1 e `setuptools` 82.0.1, cujos fixes exigem
  Python ≥3.10. A matriz larga o 3.9, o lock recompila no 3.10 (`pip` 26.2.1,
  `setuptools` 84) e o workflow não usa mais `--ignore-vuln`
- `pip install --require-hashes` no 3.10 falhava porque o pytest 9 puxa
  `exceptiongroup` só abaixo do 3.11; o lock compilado em 3.12 não pinava
  o backport. O lock passa a incluir `exceptiongroup==1.3.1`

### Added

- **Plano multi-repo baseado em evidência** (`24-evidence-based-planning`):
  dependências observadas (OpenAPI clients, imports, URLs, eventos, arquivos
  de build e contratos do Canonical Spec) passam a ser a autoridade do
  `implementation_plan`; cada aresta registra `from`/`to`, tipo, arquivo/símbolo,
  confiança e o motivo
- Grafo global detecta repositórios compartilhados e ciclos; fallback por
  camada fica `origin: heuristic` e `requires_review`;
  `ready_for_parallel_execution` só fica verdadeiro com plano `--reviewed` e
  sem conflito (ciclos e contratos ausentes bloqueiam o scheduler)
- **Evals de candidato** (`23-candidate-evals`): `improve` materializa workspaces
  distintos, aplica a proposta só no candidato e compara evals com gate por
  caso crítico (não só pass rate agregado)
- Métricas de eval passam a incluir claim recall, statuses HTTP, traceability,
  inferências inesperadas, custo (`avg_est_tokens`) e latência
- Fixtures `eval_adversarial` (HTTP exact) e `eval_multi_context`; testes de
  concorrência e recovery do apply
- Histórico de propostas guarda diff e métricas comparadas; o resultado
  distingue `proposed`, `applied_to_candidate`, `evaluated`,
  `approved_for_experiment`, `accepted` e `rejected`
- Limites aceitos neste slice (efeito do overlay no IR fica no `14`):
  `src.run` ainda lê `pipeline.yaml` do ROOT; o gate multi-contexto que
  passa é `eval_multi_context` (`two_services` segue com 401 omitido);
  suíte default maior (`--cases` restringe)
- **Tokenizer oficial pluggable** (`src/tokenizer.py`): budget e telemetria usam a
  estratégia do `models.provider` / `models.name`; OpenAI via `tiktoken`
  (`method=official`); demais providers ou lib ausente falham aberto para
  `chars÷4` com `method=heuristic` — o fallback nunca é tratado como exato
- `token_usage` no resultado da run e no `llm_package.meta`, com hook
  `observe_billable` para o live (09) persistir estimado vs tokens cobrados
- Testes de budget no limite (`== teto` cabe; `teto+1` corta template)
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
- **Gates de produção** (`25-production-quality-gates`): lock hashed
  (`requirements.lock` / `requirements-dev.lock` via pip-tools), CI com
  compile + ruff + mypy + coverage mínima **70%** (relatório por módulo),
  `pip-audit`, detect-secrets, YAML (`yaml.safe_load` + yamllint), Actions
  pinadas por SHA e `permissions: contents: read`, matriz Python **3.10–3.13**,
  artifacts eval/coverage/verify (placeholder de verify quando a run não
  executa `close_loop`). Job agregador `CI` required-ready para branch
  protection; a regra no GitHub **ainda não está ativa**
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

- **Evidência de código no Canonical Spec** (`22-code-evidence-spec`): o IR
  passa a modelar `current_state`, `gaps` e `code_evidence`; o `repo_index`
  aponta arquivo, símbolo, linha, rota e confiança, com origem `observed` ou
  `heuristic` explícita
- Método/path/status encontrados no código podem resolver campos do IR com
  `origin: observed`; conflito entre regra declarada e código observado abre
  pergunta (`open_questions`) em vez de silenciar a divergência
- História e PRD renderizam estado atual e gaps **a partir do IR**; ausência
  de índice declara *índice não aplicado* e nunca vira “sem gaps”
- Testes (`tests/integration/test_code_evidence_spec.py`): ponteiros do índice,
  resolução `observed`, conflito regra × código, render e regressão sem índice
- **Storage seguro da run** (`18-safe-run-storage`): `src/runtime/atomic_io.py`
  com write-temp + `os.replace`, cópia atômica e contenção de caminho
  (`resolve_within`)
- **Orquestração via `pipeline.yaml`** (`11-stages-yaml`): `stages` vira DAG
  executável (`handler`, `depends_on`, `gates`, `foreach: context`);
  `src/run.py` deixa de hardcodar ingest → preprocess → reason → emit
- Protocolo `Stage` + registry de handlers, checkpoints com `schema_version`,
  retry/timeout por estágio, retomada `--resume --run-id` (valida hashes das
  entradas) e cancelamento com `manifest.status: cancelled`
- Gate YAML `validation.has_errors → blocked`; handlers recusam escrita fora
  de `runs/<id>/`; runs antigas sem `checkpoints/` migram a partir de
  `events.jsonl`
- Testes em `tests/integration/test_stages_yaml.py`: estágio isolado, falha
  intermediária preserva `run_id`, resume, hash mismatch, timeout, retry,
  sandbox e migração
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
- **Hardening profundo** (`15-hardening-deep`): Agent Debugger persistido na run
  (`validations/debugger.json` com `failure` / `agent_behavior` /
  `harness_component` / `root_cause`)
- Scan de inputs (secrets, PII heurística, instruções suspeitas) **antes** de
  montar o pacote LLM; achado `error` bloqueia (`reason: input_scan_failed`) e
  grava `validations/input-scan.json`
- Tools de recovery `search_claims` e `get_claim` no `llm_package` (OpenAI/Claude
  + contrato neutro), consultando claims da run
- Golden recall (`tests/fixtures/golden/expected_claims.yaml`): o teste falha se
  o recall dos claims anotados cair
- Profiles explícitos `gtw` / `worker` / `batch` + fallback fail-closed;
  `realpath`/symlink na policy; allowlist semântica de argv; `run_argv` sempre
  com `shell=False`

### Changed

- `ready_for_parallel_execution` no relatório do plano exige plano revisado e
  ausência de conflito (ciclo, contrato ausente, repo compartilhado sem
  `coordenacao`); topologia por camada deixa de ser autoridade
- `improve` deixa de comparar a mesma eval duas vezes: baseline e candidate
  são workspaces/commits distintos; `accepted` só existe depois do apply no
  candidato
- HTTP em caso crítico passa a exigir igualdade de status, salvo regra
  explícita (`http_status_mode`) na fixture
- Budget (`context_build`) e telemetria (`est_tokens`, calculadora) passam a
  contar com o tokenizer ativo em vez de `len/4` fixo; recorte de consolidado
  ainda usa tokens×4 só como clip em caracteres
- `close_loop --approve` deixa de marcar `execution.approved = True`.
  O atalho foi removido: use `python -m src.approval`. `approved=False`
  no payload ainda gera `needs_approval` no verify; promoção exige o
  registro auditável
- Python suportado declarado como **3.10–3.13** (a matriz do CI cobre esse
  intervalo; 3.9 saiu porque os fixes de CVE do lock largaram essa versão)
- `config/tools.compact.yaml` passa a ser YAML válido (assinaturas entre aspas)
- `close_loop` / `verify_execution` exigem checkout Git (`--repo`) e log
  estruturado do adapter; `changed_files` e `commands_executed` do payload
  só servem para detectar divergência, não como evidência

- História e PRD passam a preencher estado atual e gaps a partir do Canonical
  Spec; o placeholder “sem gaps” some quando o índice não foi aplicado
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
- `--run-id` e `--resume` na CLI de `src.run`; `cancelled` entra na máquina de
  status (`failed`/`cancelled` podem voltar a `running` na retomada;
  `completed`/`blocked` continuam finais)

### Fixed

- **Operações por contexto no IR** (`29-operations-por-contexto`): o Canonical
  Spec deixa de copiar o conjunto inteiro de actions da UI para cada serviço.
  `Operation.owner` é resolvido por evidência (campo explícito na UI ou
  keywords/path do mapa); `--context` / `--all-contexts` só emitem as ops do
  serviço; `ERR-*` acompanha a operação dona e erro órfão fica `unresolved`
  (não é copiado). OpenAPI, Mermaid e futuros consumidores leem o mesmo
  `spec.operations` — o recorte não vive em cada renderer

### Riscos aceitos (`20-evidence-backed-verification`, 2026-09-18)

- Adapter Devin continua stub; o runner real grava o JSONL no `10-devin-e2e`
- Worktree sujo vs `result_commit` não é checado (verify lê o commit); débito do `10`
- Sem `PROMPTLESS_INTEGRITY_KEY`, `evidence_hashes.hmac` fica nulo (SHA-256 permanece); selo da aprovação é o `21`

### Planejado (série 2)

- Modo `--live` (OpenAI / Claude)
- Devin CLI real no `close_loop`
- Redis opcional (state backend)
- Execução concorrente por ondas
- Apply de propostas + rollback em produção (`14`; candidato já é o ticket 23)


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
