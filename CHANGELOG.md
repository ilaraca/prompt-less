# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere a [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added

- **Contexto crítico e custo completo** (`38-critical-context-budget`):
  `_fit_to_budget` reserva RF/AC/contratos/evidências (`dynamic.critical`) e
  deixa de cortar conteúdo crítico em silêncio. Omissões não-críticas trazem
  `reason` + `ref` recuperável; excesso do mínimo crítico bloqueia ou exige
  split (`CRITICAL_BUDGET_*`, `budget_report.diagnosis` / `split_plan`).
  `task_metrics` inclui `attempts` e duração de validação/reparo; custo distingue
  `estimate` vs `observed_billing` e nunca marca estimativa como fatura
  (`is_invoice=false`). Compressão/híbrido enriquecem omissões com refs.
  Testes: `tests/integration/test_critical_context_budget.py`.
- **Regressões por caso e experimento controlado** (`39-case-regression-gates`):
  `compare_evals` marca pass→fail em qualquer caso (mesmo com `pass_rate`
  agregado igual), bloqueia conjuntos incomparáveis e exige tolerância não
  crítica explícita (`justification` → `tolerances_applied`). Dimensões
  `required_gates` True→False também regressam. Promoção ignora jitter de
  latência. `improve` registra experimento (referência, candidato, diff,
  condições, `reserved_cases`; hold-out default `eval_adversarial`) e o
  candidato não pode mutar `failure-patterns` / `playbook` /
  `permission_profiles`. Hold-out permanece separado da orientação da mudança,
  mas `apply_reserved_gate` veta promoção se houver regressão/falha crítica
  (ou não crítica sem tolerância) nos casos reservados — mesmo com melhora no
  conjunto de desenvolvimento.
- **Limites efetivos do executor** (`37-executor-enforcement`):
  `EnforcedRunner` aplica writes/comandos, scrub de credenciais, timeout,
  processos/memória e negação de rede *durante* a execução; profiles ganham
  `limits` + `required_capabilities`; despacho Devin exige
  `EnforcementContract` (evidência em `enforcement-contract.json`) ou bloqueia
  (`DispatchBlocked`). Worktree/`shell=False` documentados como ≠ sandbox.
  Testes: `tests/integration/test_executor_enforcement.py`.
- **Contenção de writes nos processos filhos** (`37` ajuste pós-reabertura):
  `apply_write` sozinho não basta — `EnforcedRunner` injeta sitecustomize que
  nega `open`/`Path.write_*` fora de `repo_root`, define `TMPDIR` dentro do
  repo e, quando a sonda OS passa, envolve o filho com `sandbox-exec` (macOS)
  ou `bwrap` (Linux). Capacidade `writes` só é declarada se a contenção for
  verificada; senão `DispatchBlocked`. `EnforcedRunner` é callable
  (`runner(argv, profile=…)`) e o adapter Devin **não** o substitui por
  `run_argv` na invocação do CLI.

### Changed

- **Fingerprint do conteúdo em revisão obrigatória** (`33-required-review-gate`):
  `ReviewDecision` passa a gravar `reviewed_subject_fingerprint` (hash do texto
  do RF / given-when-then do AC / trigger do erro + evidências). Alterar o
  conteúdo com os mesmos IDs, claim e `spec.version` invalida a aprovação
  (`REQUIRED_REVIEW_STALE`); o fingerprint do claim sozinho não basta.
- **Política completa no reparo** (`36-repair-policy`): `build_repair_request`
  deixa de filtrar só padrões protegidos — reaplica profile da camada +
  `repo_root` (`resolve_repo_path` / realpath / symlink) a cada tentativa.
  Escapes (absoluto, `..`, symlink fora do repo) e writes negados vão para
  `denied_paths`; `TEST_FAILED` só amplia `editable_surface` se autorizado;
  IDs RF/AC não são caminhos; `FILE_OUT_OF_SCOPE` permanece só em
  `required_reverts`; `attempt > max` → `exhausted` com `unresolved=true`.
  `close_loop` passa profile/`--repo` e sempre re-verifica antes do repair.
- **Gates obrigatórios de avaliação** (`30-eval-required-gates`): `score_case()`
  separa diagnóstico (`layer_scores`) de aprovação (`required_gates` /
  `fail_reasons`). Dimensões obrigatórias — spec presente/com sinais, artefatos
  esperados presentes e com sinais, rastreabilidade, serviço, ausência de
  pendências bloqueantes — entram em AND e **não se compensam** (spec OK não
  salva artefato ausente). Casos `expect_blocked` validam também
  `expected_reason` / `expected_block_codes`. Rastreabilidade deixa de ser
  gate só em `critical`. O gate `traceable` exige SourceRef válido em cada
  claim (document não vazio; linhas coerentes): existência só do ID do claim
  **não** basta, e manifesto íntegro **não** compensa fonte ausente/inválida.

### Added

- **Evidência de teste independente** (`35-independent-test-evidence`):
  `_materialize_test_evidence` deixa de traduzir `passed=True` do sidecar em
  `exit_code=0` — o runner do harness executa o comando sugerido, captura
  argv/stdout/stderr/exit reais e grava binding (`run_id`, repositório,
  commits, `spec_hash`) no JSONL. Sidecar é só sugestão (`command`/`kind`/
  `covers`). Comando sem runner de teste (ex.: `git diff`), ainda que
  autorizado e com exit 0, **não** prova aceite — `kind`/`covers` do agente
  não bastam. `EnforcedRunner` é invocável como `run_argv` (`__call__` /
  `invoke_runner`). Verify exige `executed_by=harness`, rejeita log ausente/
  incompleto/adulterado/de outra run, e bloqueia AC obrigatório sem prova
  comportamental (`AC_WITHOUT_BEHAVIORAL_EVIDENCE` — arquivo existente não
  basta). Stubs/skips ficam em `evidence_hashes.test_kinds.stub_or_skip`,
  separados de E2E real. Testes em
  `tests/integration/test_independent_test_evidence.py`.
- **Revisão obrigatória bloqueante** (`33-required-review-gate`): match lexical
  com `requires_review=true` deixa de ser só warning — o gate emite
  `REQUIRED_REVIEW_PENDING` até `review_decisions` registrar ator, justificativa
  e versão revisada (spec + fingerprint do claim); aprovação compatível libera,
  rejeição e evidência/spec divergente (`REQUIRED_REVIEW_STALE`) bloqueiam;
  avisos informativos (`ORPHAN_CLAIM`, `NFR_FROM_BASELINE`) seguem não bloqueantes
- Modelo `ReviewDecision` em `src/domain/review.py`; testes de approve/reject/
  stale em `tests/integration/test_contextual_provenance.py`
- **Falha inequívoca na CLI** (`34-cli-failure-exit`): `python -m src.run`
  imprime o JSON da run e sai com código **2** quando `status` é `blocked` ou
  `failed` (sucesso continua 0). Exceções viram JSON `{status, error,
  error_type}` legível para automação
- `assert_run_ready_for_executor` (`src/runtime/consume.py`) e gate no
  `python -m src.executors.devin`: run blocked/failed ou `run_id` divergente
  não despacha; espelho `outputs/.mirror-manifest.json` com status ≠ completed
  também recusa reutilização de história antiga
- Flags `--inputs-dir` / `--output-root` em `src.run` (isolamento de testes e
  workspaces)
- Em blocked/failed, o espelho é **invalidado** (podando o que a publicação
  anterior listou) e `manifest.result_summary.reason` alinha com o JSON da CLI
- Testes de subprocesso: `tests/integration/test_cli_failure_exit.py`
- **Seleção de eval por execução** (`31-eval-run-selection`): `score_case` /
  `run_eval_suite` exigem `run_id` e carregam só artefatos listados em
  `runs/<run_id>/manifest.json` (`integrity.files`), com checagem de estado e
  sha256. Espelho `outputs/` não participa da seleção automática. Run
  `blocked` pode ser avaliada como bloqueio esperado, mas
  `artifacts_released=false` (história/PRD não liberados para implementação).
  API: `select_run_evidence`, `RunStore.sealed_file_entries` /
  `verify_sealed_entry`. Testes em `tests/integration/test_eval_run_selection.py`.
- **Evals com contratos HTTP tipados** (`32-eval-typed-http`): o gate deixa de
  extrair números de RF/AC/perguntas e passa a comparar por operação
  (`http_operations` na fixture) — serviço, método, rota, `success_status`
  resolvido e erros vinculados; sucesso ausente/pendente não presume valor;
  status correto noutro serviço/op não compensa. Fixtures da suíte default
  declaram expectativas por operação; testes cobrem os negativos.

- **Execução concorrente por ondas** (`13-parallel-exec`): scheduler
  `src/executors/scheduler.py` consome `waves` do `implementation_plan`, limita
  N tasks com semáforo (`--max-concurrency`) e agrega `ExecutionResult` + verify
  por repositório; falha numa task **não** apaga resultados das irmãs da onda
- CLI `python -m src.parallel_exec --plan … [--max-concurrency N] [--dry-run|--stub]`
  grava `parallel-report.json`; state file backend ganha compare-and-set + lock
  (`FileStateBackend`, sem Redis/`12b`)
- Testes com adapter fake paralelo:
  `tests/integration/test_parallel_exec.py`

- **Devin CLI real no close_loop** (`10-devin-e2e`): `DevinAdapter.execute`
  invoca `devin --print --prompt-file …`, grava `adapter-log.jsonl` (comandos
  de build/teste) + `devin-session.json` (metadados da sessão), commit automático
  do resultado e `execution.json` com `base_commit`/`result_commit` derivados do
  Git — não do payload do agente
- `scripts/devin-from-promptless.sh` chama `python -m src.executors.devin
  --close-loop` ao final (traço em `runs/<id>/validations/verify-report.json`)
- Worktree sujo vs `result_commit` é fail-closed (`DIRTY_WORKTREE` /
  `HEAD_NOT_RESULT_COMMIT`) antes/durante o verify
- E2E opcional: `DEVIN_E2E=1` (+ CLI autenticado); CI sem credencial faz skip
- Testes com subprocess mock: `tests/integration/test_devin_adapter.py`
- Aprovação humana continua via `python -m src.approval` (sem
  `close_loop --approve`); `promote` permanece selo em `promotion.json`

- **Modo `--live`** (`09-live-llm`): `src/reason.py` chama OpenAI Responses
  (`OPENAI_API_KEY`) ou Claude Messages (`ANTHROPIC_API_KEY`) com o
  `llm_package_*.json`; dry-run permanece o default
- Telemetria real em `token_usage` / `meta.live`: tokens billable, `delta` vs
  estimado, `cache_hit`/`cache_read_tokens` quando o vendor reporta, e
  `cost_usd` (tabela `economia.MODELOS`); falha de API não grava pacote/artefato
  live e deixa `runs/<id>/` íntegro
- Testes com transporte HTTP mock (`tests/integration/test_live_llm.py`)
- **Apply + rollback em config** (`14-apply-rollback`): `python -m src.apply`
  aplica `change.key/value` em arquivos versionados sob `config/`, grava
  snapshot de bytes em `state/knowledge/snapshots/`, re-roda a eval suite e
  restaura o snapshot se houver regressão (`rejected`)
- Risco `medium+` exige `assert_promotable` via `src.approval` (não
  `close_loop --approve`); `run` / evals mesclam `proposal-overlay.yaml` para
  baseline e candidate executarem sobre configs distintas
- Testes: aceite persiste a mudança; regressão reverte bytes; medium sem
  aprovação falha fechado
- **Recuperação híbrida de documentos** (`26-hybrid-document-retrieval`): roteador
  `structured` | `flat` em `src/hybrid_retrieval.py` — documento com títulos usa
  âncoras de seção (`doc_preface.parse_sections` + TF-IDF); documento plano mantém
  `doc_compress` (chunk + `SIGNAL_RE`) sem regressão
- Segunda camada semântica **opcional**, limitada por budget, com fallback local
  (sinônimos + cosseno TF) — funciona sem provider externo; secrets/PII são
  removidos antes dessa camada
- Cada trecho recuperado carrega `SourceRef`, `score` e `retrieval_strategy`;
  dedupe preserva diversidade de fontes; índice invertido por seção em
  `state/doc_section_index.json` (nunca no prompt)
- Telemetria de custo semântico (`est_tokens_semantic`, `hybrid` em rag_stats);
  CLI `python -m src.hybrid_retrieval FILE [--query] [--detect-only]`
- Golden fixtures `hybrid_structured` / `hybrid_synonym` / `hybrid_narrative` +
  testes em `tests/integration/test_hybrid_retrieval.py`

- **Baseline de engenharia v2** (`28-engineering-baseline-v2`): `engenharia.yaml`
  versionado (`config/engenharia.schema.yaml`); catálogo com circuit breaker,
  metrics, tracing, idempotência e segurança; NFRs selecionados por camada +
  criticidade (não o YAML integral no prompt); origem
  `baseline|declared|observed` por NFR; conflitos com o índice de código viram
  gaps; templates v1 migram na ingest; história/PRD/tasks SDD compartilham os
  mesmos IDs `NFR-*`
- Testes (`tests/integration/test_engineering_baseline_v2.py`): migração v1→v2,
  seleção por camada/criticidade, IDs alinhados e gaps NFR×código

- **Consumidor SDD** (`27-sdd-consumer`): `run sdd` (e `also_emit` de história/PRD)
  gera `sdd-package.yaml` a partir do Canonical Spec — arquitetura, API decisions
  e tasks rastreáveis para revisão humana, sem despacho a executor
- Cada task liga RF, AC, NFR, serviço e evidência; dependências reutilizam o
  grafo multi-repo (`build_implementation_plan`); perguntas abertas bloqueiam
  só o recorte afetado (`OP-*` / `ERR-*` / trigger)
- Gate `validate_sdd_package` (`config/sdd-package.schema.yaml`): source =
  `canonical-spec`, 100% das tasks com RF/AC, origem de decisão não pode ser
  `renderer`, `executor_dispatch` permanece false
- Testes (`tests/integration/test_sdd_consumer.py`): fonte IR, grafo, bloqueio
  por escopo, isolamento two_services e rejeição de despacho prematuro
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

- `LOW_CONFIDENCE_CLAIM_MATCH` (warning) substituído por erros
  `REQUIRED_REVIEW_PENDING` / `REQUIRED_REVIEW_REJECTED` / `REQUIRED_REVIEW_STALE`
  no validador de traceability — pendência obrigatória bloqueia implementação

- README: limitações do `13-parallel-exec` documentam riscos residuais aceitos
  (CLI sem Devin-por-task; onda seguinte após falha parcial; Redis/`12b` parqueado)
- README: limitações do `10-devin-e2e` documentam riscos residuais aceitos
  (sidecar para testes/build no JSONL; `DEVIN_E2E` só com CLI autenticado;
  auto-commit local sem push/PR)
- README: limitações da Onda C (`09`/`14`/`26`/`28`) documentam riscos residuais
  aceitos (Gemini ausente, overlay sem consumidor de negócio no IR, retrieval
  sem embeddings, sinais NFR por substring, etc.) e removem próximos passos já
  entregues (`--live`, apply+rollback, baseline v2, hybrid retrieval)

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
- Integração 35/37: `EnforcedRunner(profile=None)` pula allowlist do binário meta-CLI Devin; `.promptless-tmp` entra em `.git/info/exclude` para não falhar verify por worktree sujo.

- Quality-gates deixam de divergir entre a máquina e o GitHub: o workflow chama
  `python scripts/quality_gates.py` (compile, ruff, mypy, YAML, secrets, audit,
  pytest+coverage). Cada onda que só rodava pytest quebrava no mypy depois do
  push (`33d1726`, `279267f`, e de novo 24/27). Tipos dos slices 24/27
  passam no mypy; collect não falha quando o typecheck pula os testes
- `pip-audit --strict` na matriz 3.10–3.13 deixava de passar: o lock compilado
  em 3.9 pinava `pip` 26.0.1 e `setuptools` 82.0.1, cujos fixes exigem
  Python ≥3.10. A matriz larga o 3.9, o lock recompila no 3.10 (`pip` 26.2.1,
  `setuptools` 84) e o workflow não usa mais `--ignore-vuln`
- `pip install --require-hashes` no 3.10 falhava porque o pytest 9 puxa
  `exceptiongroup` só abaixo do 3.11; o lock compilado em 3.12 não pinava
  o backport. O lock passa a incluir `exceptiongroup==1.3.1`

- **Operações por contexto no IR** (`29-operations-por-contexto`): o Canonical
  Spec deixa de copiar o conjunto inteiro de actions da UI para cada serviço.
  `Operation.owner` é resolvido por evidência (campo explícito na UI ou
  keywords/path do mapa); `--context` / `--all-contexts` só emitem as ops do
  serviço; `ERR-*` acompanha a operação dona e erro órfão fica `unresolved`
  (não é copiado). OpenAPI, Mermaid e futuros consumidores leem o mesmo
  `spec.operations` — o recorte não vive em cada renderer

### Riscos aceitos (`20-evidence-backed-verification`, 2026-09-18)

- Sem `PROMPTLESS_INTEGRITY_KEY`, `evidence_hashes.hmac` fica nulo (SHA-256 permanece); selo da aprovação é o `21`
- *(mitigado pelo `10`)* Adapter Devin deixou de ser stub; worktree limpo é exigido no verify

### Planejado (série 2)

- Redis opcional (state backend) (`12b`)
- Client `--live` para Gemini / embeddings opcionais na retrieval híbrida
- Alertas / ADRs / bulkhead no catálogo de engenharia (extensão do `28`)

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
  e policy de camada, aprovação e reparo limitado; adapter Devin (CLI real no `10`)
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
