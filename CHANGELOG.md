# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere a [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Planejado (série 2)

- IR → OpenAPI / Mermaid a partir do Canonical Spec
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
