# Prompt-less

> Gera OpenAPI, fluxo Mermaid, história técnica (funcional + NFR) e PRD a partir de Figma, regras, engenharia e docs — com contexto comprimido, custo de tokens sob controle e **engineering harness** (runtime, provenance, Canonical Spec, verify e melhoria controlada).

**Repositório:** [github.com/ilaraca/prompt-less](https://github.com/ilaraca/prompt-less) · **Changelog:** [CHANGELOG.md](./CHANGELOG.md)

Pipeline de tech lead que transforma insumos desidratados (UI, regras, `engenharia.yaml`, TXT/DOCX) em artefatos: contrato de API, diagrama de sequência, história BFF/MFE (BDD + DoD técnico) e **PRD.md** (insumo para SDD). Em vez de mandar tudo ao LLM, filtra o sinal, comprime o contexto e só então gera. Cada execução isola estado em `runs/<run_id>/`, emite um **Canonical Spec** verificável e registra claims com proveniência.

Inspirada nas práticas descritas por Yuval Ben-itzhak (*How I reduced LLM token costs by ~90%*): o custo real não está no prompt “bonito”, e sim na **explosão de contexto** (system repetido, tools verbosas, histórico, RAG bruto, logs).

---

## Objetivo

Receber insumos de produto/UX/negócio e emitir **artefato(s) finais sem prosa**, com:

- contexto **comprimido e estruturado** antes do modelo de raciocínio;
- estado do workflow **fora do prompt**;
- prefixo de system/tools **estável e cacheável** (OpenAI / Claude);
- budget explícito de tokens (alvo ~650; teto ~2000);
- **PRD.md** gerado junto com a história, como insumo canônico para **SDD**;
- baseline de engenharia (**stack + NFR v2**: timeout/retry/circuit breaker/
  metrics/tracing/idempotência/segurança, selecionados por camada/criticidade)
  via `inputs/engenharia.yaml` (schema versionado);
- **harness**: runtime por `run_id`, provenance/claims, Canonical Spec + quality gate,
  ciclo verify/repair, plano multi-repo, melhoria com evals e `src.apply` (config
  versionada com snapshot/rollback).

**Princípio:** nunca enviar dados brutos ao modelo se puderem ser filtrados ou comprimidos antes.

---

## Aplicabilidade

### Onde esta pipeline faz sentido

| Cenário | Por quê |
|--------|---------|
| **Geração assistida de contratos OpenAPI** a partir de Figma + regras | Inputs/listas viram schemas; bloqueios viram 4xx tipados |
| **Diagramas de sequência Frontend → BFF → API** | Traduz regras em `alt`/`opt` sem reenviar specs inteiras |
| **Histórias técnicas BFF/MFE** (BDD + DoD NFR) | Funcional = `regras.yaml`; técnico = `engenharia.yaml` (stack, retry, logs, docs) |
| **PRD.md para SDD (Spec-Driven Development)** | `historia` emite também o PRD com RF/AC, contrato de dados, NFR-R/O/S/D e handoff |
| **Onboarding / tech lead docs** | Padroniza artefatos a partir de fontes heterogêneas |
| **Specs longas (milhares de linhas)** | Compressão hierárquica: sinal de negócio entra; ruído sai |
| **Agentes multi-etapa com custo controlado** | State externo + pacote LLM enxuto por request |
| **Handoff para Devin CLI** | `outputs/` / `docs/prompt-less/` como contexto curto para implementação |
| **Microsserviços / multi-repo** | `scan-repos.sh` lê a pasta de repos → mapa → marcadores → `outputs/contextos/<id>/` |
| **Pré-processamento barato + raciocínio caro** | Camada local (“modelo pequeno”) + slot para LLM grande |
| **Gate antes de implementar** | Canonical Spec bloqueia ambiguidade (ex.: HTTP indefinido) com `PipelineBlocked` |
| **Verify pós-executor** | `close_loop` confere o que ocorreu no Git e nos logs do adapter (não o payload) vs spec + policy |
| **Promoção com aprovação humana** | `src.approval` vincula ator + spec + relatório + commit; HMAC detecta adulteração |
| **Plano coordenado multi-repo** | `plan_repos` gera ondas/contratos a partir de dependências observadas (código + Canonical Spec); camada é fallback revisável |
| **Melhoria sem regressão silenciosa** | `improve` aplica a proposta só no candidato, compara evals distintas e só então promove status |

### Onde *não* é a melhor ferramenta (ainda)

| Cenário | Motivo |
|--------|--------|
| Geração 100% automática em produção sem revisão humana | `--live` chama OpenAI/Claude, mas revisão humana + gates de IR continuam; apply em config exige risco `low` ou aprovação (`21`); Devin E2E grava evidência e exige `src.approval` antes do promote |
| Documentos sem sinais lexicais de negócio | Resumo extrativo prioriza termos (regra, HTTP, endpoint…); texto só narrativo pode ser filtrado demais |
| Extração fiel linha a linha de PDFs jurídicos/contratos | Foco é **sinal para artefato técnico**, não arquivo íntegro |
| `.doc` legado fora do macOS sem `antiword` | Conversão depende de `textutil` (macOS) ou `antiword` |

### Público-alvo

- Tech Leads / Arquitetos montando pipeline de artefatos e PRD→SDD
- Times de plataforma de IA que precisam **orçar tokens**
- Squads BFF/MFE que partem de Figma + regras desidratadas

---

## Arquitetura

```
Dados brutos (figma.json, regras.yaml, engenharia.yaml, *.txt/*.docx/*.doc/*.md)
        │
        ▼
   [ingest] ─────────────── carrega só o necessário
        │
        ▼
 [preprocess] ───────────── desidrata UI/regras/engenharia; docs com metadados+texto
        │
        ▼
 [state_write] ──────────── runs/<run_id>/ + state SEM texto bruto
        │
        ├──────────────────► docs: chunk → resumo (sinais) → consolidado
        │
 [rag_compress] ─────────── UI/regras/engenharia + docs → consolidated ≤ budget
        │                   (+ claims / discarded → provenance.json)
        ▼
 [canonical_spec] ───────── IR verificável + quality gate (bloqueia se erros)
        │
        ▼
 [context_build] ────────── system estável (cache) + dynamic enxuto
        │
        ▼
   [reason] ─────────────── pacote OpenAI/Claude  |  dry-run scaffold
        │
        ▼
    [emit] ──────────────── artifacts/ + espelho outputs/
                            openapi | sequence.mmd | historia.md | PRD.md | sdd-package.yaml | canonical-spec.yaml

        (pós-execução, opcional)
 [close_loop] ───────────── Git diff × adapter log × spec × policy → verify / repair
 [approval] ─────────────── request-approval → approve|reject → promote (HMAC)
 [plan_repos] ───────────── mapa + evidência de código/contratos → implementation_plan (ondas)
 [improve] ──────────────── diagnose → apply no candidato → evals distintas → accepted / approved_for_experiment / rejected
 [apply] ────────────────── snapshot → change.key/value em config/ → re-eval → keep ou rollback
```

### Técnicas de economia de tokens (mapeamento do artigo)

| Técnica do artigo | Implementação nesta pipeline |
|-------------------|------------------------------|
| Não reenviar histórico completo | `state/workflow.json` com campos mínimos |
| Tools compactas | `config/tools.compact.yaml` (assinaturas curtas) |
| System prompt estável / cache | `prompts/system.compact.txt` + pacote Claude `cache_control` |
| Comprimir RAG | `rag_compress.py` + `doc_compress.py` |
| Compressão hierárquica | chunks → resumos → consolidado |
| Modelo pequeno no pré-processamento | Extrativo local (regex de sinais); slot para LLM small depois |
| Encadeamento OpenAI Responses | Pacote com `store: true` (pronto para `previous_response_id`) |
| Budget de contexto | `config/pipeline.yaml` → `max_context_tokens: 2000` |

---

## Como a estrutura funciona (camada a camada)

A orquestração está declarada em `config/pipeline.yaml` (`stages` com `handler`, `depends_on`, `gates`). `src/run.py` carrega o grafo e o executa; cada etapa continua num módulo próprio e o dado flui **sempre desidratando**.

### 1. `ingest` (`src/ingest.py` + `src/docs_ingest.py`)

**Papel:** carregar insumos do disco, sem transformar ainda.

| Fonte | Módulo | O que entra |
|-------|--------|-------------|
| `inputs/figma.json` | `ingest.py` | JSON da UI |
| `inputs/regras.yaml` | `ingest.py` | YAML de negócio |
| `inputs/engenharia.yaml` | `ingest.py` | Stack, padrões, arquitetura, NFR baseline |
| Template do tipo pedido | `ingest.py` | esqueleto OpenAPI / Mermaid / História / PRD |
| `*.txt`, `*.md`, `*.docx`, `*.doc` | `docs_ingest.py` | texto extraído + metadados (`name`, `lines`, `chars`, `est_tokens_raw`) |

- `.docx` → `python-docx` (parágrafos + tabelas).
- `.doc` → `textutil` (macOS) ou `antiword`.
- `README.txt` em `inputs/` é ignorado de propósito.

**Saída desta etapa:** um dict `raw` com `tipo`, `figma`, `regras`, `engenharia`, `template`, `documents[]`.

### 2. `preprocess` (`src/preprocess.py`)

**Papel:** camada “modelo pequeno” **local** (sem LLM) — tira metadados visuais e prosa.

- **Figma** → só `inputs` (nome/tipo/required), `actions` (id/method/path), `columns` (nome/tipo). Tipos são inferidos (`idade`→integer, etc.).
- **Regras** → `fluxo`, `happy`, `bloqueios` (trigger + status HTTP), `decisoes`.
- **Engenharia** → `stack`, `padroes`, `arquitetura`, `resiliencia`, `observabilidade`, `seguranca` (defaults se o arquivo faltar).
- **Docs** → mantém texto **só nesta etapa intermediária** para a compressão; o state depois descarta o corpo.

**Saída:** `slim` = UI + regras + engenharia desidratadas + documents + template.

### 3. `state_write` (`src/state_store.py`)

**Papel:** substituir histórico de conversa por **estado externo** (padrão do artigo).

Grava em `state/workflow.json` apenas:

- `tipo`, `fluxo`, nomes de `inputs`, `actions`, `bloqueios`
- recorte de `engenharia` (stack, resiliência, logs — sem YAML bruto completo se não necessário)
- metadados dos docs (`name`, `lines`, `est_tokens_raw`)
- `previous_actions`, `status`

**Não grava** o texto dos documentos nem o Figma bruto. Assim, requests seguintes (quando houver agent loop) não reenviam 3000 linhas.

### 4. Compressão de documentos (`src/doc_compress.py`)

**Papel:** compressão hierárquica de texto longo **antes** de misturar com UI/regras.

```
documento (N linhas)
    → chunks de 40 linhas (config: doc_lines_per_chunk)
        → resumo extrativo por chunk (só linhas com SIGNAL_RE)
            → lista de resumos ranqueada
                → consolidado ≤ ~800 chars (~200 tokens)
```

`SIGNAL_RE` detecta termos de negócio/API, por exemplo: `regra`, `bloqueio`, `http`, `endpoint`, `path`, `request`, `response`, `dado`, `quando`, `então`, `auth`, `permiss`, `api`, `bff`, `status`, `openapi`, `fluxo`…

- Chunk **sem** sinal → resumo vazio (ruído/telemetria descartados).
- Consolidado prioriza resumos com sinal e respeita o budget de caracteres.

### 5. Camada RAG (`src/rag_compress.py`) — o que é e o que não é

Esta pipeline usa um **RAG estrutural / lexical**, não um RAG vetorial clássico.

#### O que RAG significa aqui

O padrão **Retrieve → Augment → Generate** aparece assim:

| Etapa RAG clássica | Nesta pipeline |
|--------------------|----------------|
| **Retrieve** | Selecionar e fatiar o que já está nos insumos da execução (UI, regras, docs em `inputs/`) |
| **Augment** | Comprimir e juntar num `consolidated` ≤ budget |
| **Generate** | Montar pacote LLM / dry-run scaffold / chamada `--live` (OpenAI Responses ou Claude Messages) |

Fluxo interno de `compress_rag()`:

```
UI + regras desidratadas          Documentos (texto)
        │                                  │
        ▼                                  ▼
 retrieve_chunks()                  compress_documents()
 (1 chunk por inputs,               (chunk → sinal → consolidado
  columns, actions,                  documental)
  cada bloqueio, cada decisão)
        │                                  │
        ▼                                  ▼
 resumos curtos (~160 chars)        consolidado docs
        │                                  │
        └──────────┬───────────────────────┘
                   ▼
         consolidated final ≤ budget
         (mistura estrutural + docs)
```

Esse `consolidated` é o que vai para o campo `contexto_comprimido` do pacote LLM.

#### O que esta implementação **não** faz (RAG vetorial)

| Recurso típico de RAG “full” | Status aqui |
|------------------------------|-------------|
| Embeddings (OpenAI, sentence-transformers, etc.) | Não (2ª camada híbrida = sinônimos locais + TF) |
| Vector DB (Chroma, Pinecone, pgvector…) | Não |
| Similarity search / top-k por query | Não |
| Índice persistente entre execuções | **Sim** — `state/repo_index.json` (código dos repos, ver seção 13) |
| Reranker cross-encoder | Não |
| Ponderação por IDF | **Sim** — no de/para de serviços (`src/marcar.py`) |

**Por quê assim?** O corpus por execução é **pequeno e conhecido** (Figma + regras + poucos docs da pasta `inputs/`). Para esse caso, retrieve estrutural + filtro lexical é mais barato, determinístico e suficiente para controlar tokens. RAG vetorial passa a valer quando houver **base grande** (wiki, Confluence, dezenas de specs) e queries variáveis.

#### Analogia rápida

- **RAG desta pipeline:** “pegue estes arquivos desta pasta, fatie, filtre o que parece regra/API, comprima, entregue ao modelo.”
- **RAG vetorial:** “indexe milhares de docs; para esta pergunta, busque os k trechos mais similares semanticamente.”

Além do caminho flat (`doc_compress`), o roteador em `src/hybrid_retrieval.py`
classifica o insumo (`structured` | `flat`). Documento com títulos usa âncoras
de seção (`doc_preface.parse_sections` + TF-IDF); documento plano mantém
chunk + `SIGNAL_RE`. Segunda camada semântica é **opcional** e limitada por
budget (fallback local com sinônimos — sem provider externo). Secrets/PII são
scrubados antes. Índice invertido por seção em `state/doc_section_index.json`
(como `repo_index`), **não** no prompt.

Evolução natural (próximo passo): manter `doc_compress` / budget e trocar só o **Retrieve** por embeddings + top-k, sem mudar o resto do pipeline.

### 6. `context_build` (`src/context_builder.py`)

**Papel:** montar o prompt em duas partes (favorável a **prompt caching**):

1. **`system`** — texto fixo de `prompts/system.compact.txt` (prefixo estável).
2. **`dynamic`** — JSON enxuto:
   - `comando` (`Gerar openapi|mermaid|historia|prd`)
   - `state` (metadados, sem docs brutos)
   - `contexto_comprimido` (saída do RAG)
   - `template` (esqueleto; se estourar budget, trunca o template)

Estimativa de tokens: tokenizer do provider configurado em `models.provider` / `models.name` (`tiktoken` para OpenAI). Se a lib oficial não estiver disponível, fail-open para `chars÷4` com `method=heuristic` — o fallback **não** é contagem exata.

### 7. `reason` (`src/reason.py`)

**Papel:** preparar a geração, sem prosa na saída.

- **`build_llm_package`**: gera JSON dual:
  - `openai`: `instructions` + `input` + `store: true` + tools `search_claims` / `get_claim`
  - `claude`: `system` com `cache_control: ephemeral` + `messages` + as mesmas tools
  - `tools`: contrato neutro das duas functions de recovery sobre claims da run
- Antes de montar o pacote, o estágio `reason` varre inputs não confiáveis (secrets, PII heurística, instruções suspeitas). Achado `error` **bloqueia** a run (`reason: input_scan_failed`) e grava `validations/input-scan.json` — não engole o achado.
- **`src/renderers/`**: com Canonical Spec disponível, os artefatos são renderizados do IR (`render_historia`, `render_prd`, `render_openapi`, `render_mermaid`, `render_sdd`).
- **`dry_run_scaffold`**: fallback legado (sem IR) que preenche o template localmente, sem API.
- Na história/PRD, o render usa o IR + **`engenharia`** + `consolidated` (RF/AC + stack/NFR + handoff SDD). Estado atual e gaps saem de `current_state` / `gaps` do Canonical Spec — sem índice a seção declara *índice não aplicado*, nunca “sem gaps”.
- **`--live`**: chama OpenAI Responses ou Claude Messages consumindo o `llm_package_*.json` já comprimido (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).

### 8. `emit` (`src/emit.py` + `also_emit` em `run.py`)

**Papel:** gravar o arquivo do tipo pedido em `outputs/` (+ `llm_package_*.json`).

- Um tipo → um arquivo principal (`openapi.yaml`, `sequence.mmd`, `historia.md`, `PRD.md`, `sdd-package.yaml`).
- Exceção: `historia` declara `also_emit: [prd, sdd]` em `config/pipeline.yaml` — `run.py` gera **história, PRD e pacote SDD** na mesma execução. `prd` também emite o SDD.

### Diagrama de dados (o que viaja vs o que para)

```
figma.json ──────► preprocess ──► ui {inputs, actions, columns} ──┐
regras.yaml ─────► preprocess ──► regras {bloqueios, …} ──────────┤
engenharia.yaml ► preprocess ──► engenharia {stack, NFR v2 selecionados} ─┼─► rag_compress ─► consolidated
docs *.txt ──────► doc_compress ─► resumos/consolidado docs ─────┘         │
                                                                            ▼
state/workflow.json ◄── só metadados                               context_builder
                                                                            │
                                                                            ▼
                                                                   llm_package_*.json
                                                                   + artefato(s) em outputs/
                                                                   (historia → também PRD.md + sdd-package.yaml)
```

---

## Artefatos gerados

| Comando | Template | Saída |
|---------|----------|--------|
| `openapi` | `templates/openapi.skeleton.yaml` | `outputs/openapi.yaml` derivado do IR (+ `canonical-spec.yaml` na run) |
| `mermaid` | `templates/mermaid.skeleton.md` | `outputs/sequence.mmd` derivado do IR |
| `historia` | `templates/historia.skeleton.md` | `outputs/historia.md` **+** `outputs/PRD.md` **+** `outputs/sdd-package.yaml` |
| `prd` | `templates/prd.skeleton.md` | `outputs/PRD.md` **+** `outputs/sdd-package.yaml` |
| `sdd` | `templates/sdd.skeleton.yaml` | `outputs/sdd-package.yaml` derivado do Canonical Spec |

Toda run também grava **`canonical-spec.yaml`** e validações em `runs/<run_id>/` (espelhadas conforme o layout da execução). `historia` emite também o **PRD** e o **pacote SDD** (`also_emit` em `config/pipeline.yaml`): a história é o recorte de implementação (**BDD funcional + DoD NFR**); o PRD documenta RF/AC/NFR; o SDD é o pacote rastreável (arquitetura, API decisions, tasks) para revisão humana.

Além do artefato, a pipeline grava o **pacote LLM** (contexto já comprimido):

- `outputs/llm_package_openapi.json`
- `outputs/llm_package_mermaid.json`
- `outputs/llm_package_historia.json`
- `outputs/llm_package_prd.json`

Cada pacote inclui variantes `openai` e `claude` consumidas pelo modo `--live`.

### PRD → SDD

O `PRD.md` nasce com:

- **frontmatter YAML** (`id`, `artifacts`, `sdd.expected`, `nfr_ids`) para parsers de SDD
- RF (`RF-xx`) a partir das regras/UI
- AC (`AC-xx`) BDD alinhados à história
- NFR (`NFR-R|O|S|D-xx`) a partir de `engenharia.yaml` (baseline v2, selecionados)
- contrato de dados (entrada/saída/ações)
- seção **Handoff para SDD** (o que o próximo estágio deve gerar)
- contexto comprimido do Prompt-less (sem texto bruto)

O consumidor SDD **não lê o PRD como fonte de verdade**. Ele lê o **Canonical Spec** (`contract_operations()`, RF/AC/NFR, `current_state`/`gaps`, perguntas abertas) e emite `sdd-package.yaml`:

- **architecture** — serviço, repos, operations contratuais, estado/gaps do IR; topologia reutiliza o grafo multi-repo (ainda heurístico por camada se o 24 não descobriu deps)
- **api_decisions** — só `spec.contract_operations()`; method/path/status/origem vêm do IR (zero decisão crítica inventada pelo renderer)
- **tasks** — uma por (nó do grafo × operação contratual), cada uma com RF, AC, NFR, serviço e evidência; `depends_on` copia as arestas do plano
- **perguntas** — `blocking` só marca as tasks cujo recorte (OP/ERR/trigger) casa; pergunta sem escopo fica em `review.unscoped_questions`
- **revisão** — `executor_dispatch: false` e `ready_for_executor: false`; o pacote não chama executor

A saída passa por `validate_sdd_package` (schema em `config/sdd-package.schema.yaml`). Divergência bloqueia o emit (`reason: derived_artifact_divergence`).

```bash
.venv/bin/python -m src.run sdd --dry-run
.venv/bin/python -m src.run sdd --all-contexts --dry-run
# → outputs/sdd-package.yaml  (ou contextos/<svc>/sdd-package.yaml)
```

Fluxo:

```
Figma + regras + docs
        → Prompt-less (Canonical Spec)
                → SDD consome o IR
                        → architecture / api_decisions / tasks (pending_review)
```

### Regras de tradução

**OpenAPI** (já vale no dry-run: `render_openapi(spec)` lê o Canonical Spec)

- `operations[].request_schema` → propriedades de `requestBody` (só em POST/PUT/PATCH)
- `operations[].response_schema` (listas/tabelas da UI) → schema da resposta de sucesso
- `errors` do IR → respostas `4xx` referenciando `components.schemas.Error`,
  com `x-error-ids`, `x-error-codes` e `x-source-claims`
- `{param}` no path → `parameters` obrigatórios tipados pelo schema do IR
- sem evidência no IR → `x-unresolved` na operação, `x-unresolved-operations`
  no documento; **nenhum** `200`/`201` inventado

**Mermaid** (`render_mermaid(spec)`)

- Atores fixos: Frontend (Tela), BFF, API de Domínio
- `errors` da operação → blocos `alt` rotulados com `OP-xxx` + `ERR-xxx`
- Verbos/paths vêm de `operations`; status de sucesso não resolvido aparece como
  `sucesso não resolvido no IR — requer revisão humana`

**História**

- Título, Contexto (1 linha), Critérios BDD (Dado/Quando/Então), Dependências
- Critérios = tradução das condições de `regras.yaml`
- Payloads alinhados ao Figma
- Escopo técnico + DoD NFR a partir de `engenharia.yaml` (baseline v2)

**PRD**

- Preencher `prd.skeleton.md` sem remover o frontmatter
- RF/AC rastreáveis; dados da UI; regras → erros HTTP
- NFR-R / NFR-O / NFR-S / NFR-D a partir do baseline de engenharia
- Handoff SDD lista artefatos esperados + rastreio RF/AC/NFR

**SDD** (`render_sdd(spec)` / `run sdd`)

- Fonte primária: Canonical Spec, não o markdown do PRD
- `operations` já fatiadas no IR (`contract_operations()`); o consumidor não recorta de novo
- Tasks 100% ligadas a pelo menos um RF e um AC; NFR, serviço e evidência sempre presentes no registro
- Dependências = grafo `build_implementation_plan` (camadas heurísticas até o 24 evoluir)
- Nenhuma task vai a executor neste estágio

---

## Insumos suportados

Coloque os arquivos em `pipeline/inputs/`:

| Arquivo / padrão | Obrigatório? | Uso |
|------------------|--------------|-----|
| `figma.json` | Não | Inputs, botões/actions, colunas de lista |
| `regras.yaml` | Não | Happy path, bloqueios, tabela de decisão |
| `engenharia.yaml` | Não | Stack, padrões, arquitetura, NFR baseline (retry, logs, documentação…) |
| `mapa-servicos.yaml` | Não | Keywords/marcadores → serviço + repos (microsserviços) |
| `*.txt`, `*.md` | Não | Specs/notas longas (comprimidas; podem ter `## Serviço:`) |
| `*.docx` | Não | Word moderno (`python-docx`) |
| `*.doc` | Não | Word legado (`textutil` no macOS ou `antiword`) |

`README.txt` em `inputs/` é **ignorado** na ingestão de documentos.

### Exemplo mínimo de `engenharia.yaml`

```yaml
version: 1
stack:
  bff: [Java 17, Spring Boot 3]
  mfe: [TypeScript, React]
padroes: [hexagonal, openapi-first, bff-for-frontend]
arquitetura:
  fluxo: MFE -> BFF -> API Domínio
  contrato: openapi
resiliencia:
  timeout_ms: 2000
  retry:
    max_attempts: 2
    backoff: exponential
observabilidade:
  logs:
    formato: structured_json
    campos_minimos: [timestamp, level, service, correlation_id, message]
    sem_pii: true
seguranca:
  validar_input: true
documentacao:
  readme:
    obrigatorio: true
    secoes_minimas:
      - proposito
      - como-rodar-local
      - arquitetura
      - endpoints-ou-contratos
      - variaveis-de-ambiente
      - ownership
  changelog:
    obrigatorio: true
    formato: keep-a-changelog
    path: CHANGELOG.md
  api_docs:
    obrigatorio: true
    por_linguagem:
      java: javadoc
      typescript: tsdoc
      python: docstring
      go: godoc
```

Baseline **v1**: timeout/retry + logs + segurança mínima + **documentação** (README estruturado, CHANGELOG, docs de API conforme a stack — Javadoc, TSDoc, GoDoc…). Circuit breaker, metrics, tracing, ADRs e alertas ficam comentados/`_(futuro)_` para evoluir sem estourar tokens.

A seção `documentacao` vira **NFR-D** na história/PRD. O padrão de doc de código é derivado da `stack` (ex.: BFF Java → Javadoc; MFE TypeScript → TSDoc); `por_linguagem` só sobrescreve quando necessário.

### Exemplo mínimo de `figma.json`

```json
{
  "inputs": [
    { "name": "nome", "type": "string", "required": true },
    { "name": "idade", "type": "integer" },
    { "name": "email" }
  ],
  "buttons": [
    { "id": "salvar", "method": "POST", "path": "/clientes" }
  ],
  "columns": ["id", "nome", "status"]
}
```

### Exemplo mínimo de `regras.yaml`

```yaml
fluxo: Cadastro de Cliente
bloqueios:
  - trigger: CPF inválido
    status: 400
    code: CPF_INVALIDO
  - trigger: sem autenticação
    status: 401
  - trigger: sem permissão admin
    status: 403
decisoes:
  - quando: saldo negativo
    entao: rejeitar 422
```

---

## Comportamento com textos longos (ex.: 3000 linhas)

1. **Ingest** lê o arquivo completo (não ignora).
2. **Chunk** em blocos de `doc_lines_per_chunk` (default **40 linhas**).
3. **Resumo por chunk**: mantém apenas linhas com **sinais** de negócio  
   (ex.: regra, bloqueio, HTTP, endpoint, path, dado/quando/então, auth, permissão…).
4. **Consolidado** ≤ `consolidated_summary_max_tokens` (~200 tokens / ~800 chars).
5. **State** guarda só metadados (`name`, `lines`, tokens brutos) — **sem** o texto.
6. O **LLM recebe o consolidado**, não as 3000 linhas.

### Resultado medido (amostra incluída)

Com `inputs/amostra_3000.txt` + `inputs/amostra_regras.docx`:

| Métrica | Valor aproximado |
|--------|-------------------|
| Tokens brutos (docs) | ~48 000 |
| Tokens no RAG comprimido | ~80–200 |
| Redução documental | ~**99,8%** |
| Pacote LLM final (`est_tokens`) | ~**600–750** |
| Ruído tipo “telemetria” no prompt | **não entra** |
| Sinais (HTTP, regras, endpoints) | **preservados** |

Se o documento **não tiver sinais lexicais**, o consolidado pode ficar vazio ou muito curto — nesse caso, enriqueça o texto com termos de regra/API ou ajuste `SIGNAL_RE` em `src/doc_compress.py`.

---

## Como executar

### Setup

```bash
cd pipeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Dry-run (padrão — sem chamar API)

Gera scaffold do artefato + pacote LLM comprimido:

```bash
.venv/bin/python -m src.run openapi --dry-run
.venv/bin/python -m src.run mermaid --dry-run
.venv/bin/python -m src.run historia --dry-run   # → historia.md + PRD.md
.venv/bin/python -m src.run prd --dry-run        # só PRD.md
```

### Live (API)

Por padrão a pipeline é **dry-run** (sem rede). Com `--live`, `src/reason.py` envia o `llm_package_*.json` ao vendor conforme `models.provider` em `config/pipeline.yaml`:

| Provider | API | Variável de ambiente |
|---|---|---|
| `openai` (default) | OpenAI Responses (`/v1/responses`) | `OPENAI_API_KEY` |
| `anthropic` | Claude Messages (`/v1/messages`) | `ANTHROPIC_API_KEY` |

```bash
export OPENAI_API_KEY=sk-...          # ou ANTHROPIC_API_KEY=...
export PROMPTLESS_INTEGRITY_KEY="$(openssl rand -hex 32)"
.venv/bin/python -m src.run historia --live
```

Telemetria real grava em `token_usage` / `llm_package.meta`: `billable`, `delta` (vs estimado), `cache_hit` / `cache_read_tokens` quando o vendor reporta, e `cost_usd` (tabela de `src/economia.py`). Falha de API aborta o estágio `reason` **sem** gravar o pacote/artefato live daquele tipo — `runs/<id>/` permanece íntegro (manifest `failed`).

### Testes e CI

```bash
# reproduzível (mesmo lock do CI)
.venv/bin/pip install --require-hashes -r requirements-dev.lock
.venv/bin/pytest -q
```

O workflow `.github/workflows/ci.yml` (`name: CI`) é o check required-ready:
compile, ruff, mypy, coverage ≥ 70% (relatório por módulo), pytest (incluindo
testes adversariais de runtime/policy/provenance), `pip-audit`, detect-secrets,
validação YAML, artifacts de eval/coverage/verify. Actions pinadas por SHA,
`permissions: contents: read`, matriz Python 3.10–3.13.

Regenerar o lock: `pip-compile --generate-hashes --allow-unsafe --output-file=requirements.lock requirements.in` e o equivalente para `requirements-dev.lock`. Detalhe em [Gates de qualidade](#gates-de-qualidade).

## Exemplos de uso

Os exemplos abaixo assumem que você está em `pipeline/` com o venv ativo (ou use o prefixo `.venv/bin/python`). A trilha de eventos é assinada: exporte `PROMPTLESS_INTEGRITY_KEY` (≥16 caracteres) antes de `src.run` — sem ela o bootstrap falha fechado. Rotação: `PROMPTLESS_INTEGRITY_KID=v2` na chave nova e `PROMPTLESS_INTEGRITY_KEYS=v1=<antiga>` para verificar runs velhas.

```bash
export PROMPTLESS_INTEGRITY_KEY="$(openssl rand -hex 32)"
export PROMPTLESS_INTEGRITY_KID=v1
```

### 1. Quickstart com os insumos de exemplo

O repositório já traz `inputs/figma.json`, `inputs/regras.yaml`, `inputs/engenharia.yaml` e docs de amostra.

```bash
# História técnica (BDD + NFR) + PRD + pacote SDD
.venv/bin/python -m src.run historia --dry-run

# Ver saídas (seção NFR na história e no PRD)
ls outputs/historia.md outputs/PRD.md outputs/sdd-package.yaml
sed -n '/## Não-funcionais/,/## Dependências/p' outputs/historia.md
```

Saída esperada no terminal (resumo):

```json
{
  "outputs": {
    "historia": ".../outputs/historia.md",
    "prd": ".../outputs/PRD.md",
    "sdd": ".../outputs/sdd-package.yaml"
  },
  "est_tokens": 580,
  "rag": { "raw": 48000, "compressed": 150, "doc_reduction_pct": 99.8 }
}
```

### 2. Gerar o pacote técnico completo (API + fluxo + história + PRD)

```bash
.venv/bin/python -m src.run openapi --dry-run
.venv/bin/python -m src.run mermaid --dry-run
.venv/bin/python -m src.run historia --dry-run
```

Artefatos:

| Arquivo | Uso |
|---------|-----|
| `outputs/openapi.yaml` | Contrato derivado do Canonical Spec |
| `outputs/sequence.mmd` | Sequência Frontend → BFF → API derivada do Canonical Spec |
| `outputs/historia.md` | História BFF/MFE (BDD) |
| `outputs/PRD.md` | PRD canônico (RF/AC/NFR + handoff) |
| `outputs/sdd-package.yaml` | Pacote SDD para revisão humana (arquitetura, API, tasks) |

### 3. Só o PRD / só o SDD

```bash
.venv/bin/python -m src.run prd --dry-run
.venv/bin/python -m src.run sdd --dry-run
cat outputs/sdd-package.yaml
```

### 4. Colocar seus próprios insumos

```bash
# 1) Substitua / adicione arquivos em inputs/
cp ~/Downloads/minha-tela.json inputs/figma.json
cp ~/Downloads/regras-negocio.yaml inputs/regras.yaml
cp ~/Downloads/engenharia-plataforma.yaml inputs/engenharia.yaml   # opcional
cp ~/Downloads/spec-produto.docx inputs/

# 2) Rode o artefato desejado
.venv/bin/python -m src.run historia --dry-run

# 3) Revise o pacote SDD (não envie a executor ainda)
cat outputs/sdd-package.yaml
```

Formato mínimo de `figma.json`, `regras.yaml` e `engenharia.yaml`: ver seção [Insumos suportados](#insumos-suportados).

### 5. Spec longa (milhares de linhas) + compressão

```bash
# Amostra de 3000 linhas já inclusa
wc -l inputs/amostra_3000.txt

.venv/bin/python -m src.run openapi --dry-run

# Conferir que o pacote LLM NÃO carrega o texto bruto
.venv/bin/python -c "
import json
p = json.load(open('outputs/llm_package_openapi.json'))
d = p['openai']['input']
print('est_tokens', p['meta']['est_tokens'])
print('tem_ruido_telemetria', 'ruido de telemetria' in d)
print('rag', p['meta']['rag_stats'])
"
```

### 6. Inspecionar o pacote LLM (antes do `--live`)

```bash
.venv/bin/python -m src.run mermaid --dry-run

# Prefixo estável (cacheável) vs payload dinâmico
.venv/bin/python -c "
import json
p = json.load(open('outputs/llm_package_mermaid.json'))
print('comando:', p['meta']['comando'])
print('system_chars:', len(p['openai']['instructions']))
print('input_chars:', len(p['openai']['input']))
print('claude_cache:', p['claude']['system'][0].get('cache_control'))
"
```

### 7. Fluxo Prompt-less → SDD

```bash
# A) Prompt-less gera o canônico
.venv/bin/python -m src.run historia --dry-run

# B) (opcional) complete contrato e sequência na mesma pasta
.venv/bin/python -m src.run openapi --dry-run
.venv/bin/python -m src.run mermaid --dry-run

# C) Pacote SDD já sai de `run historia` / `run sdd` a partir do Canonical Spec
#    (não do frontmatter do PRD). Revisar tasks antes de qualquer executor.
grep -E 'source:|executor_dispatch:|status:' outputs/sdd-package.yaml | head
```

### 8. Ajustar budget e reexecutar

Em `config/pipeline.yaml`:

```yaml
budget:
  max_context_tokens: 2000
  consolidated_summary_max_tokens: 200
  doc_lines_per_chunk: 40
```

```bash
# Depois de editar o YAML, rode de novo — o consolidated muda
.venv/bin/python -m src.run prd --dry-run
```

### 9. Estado externo (sem histórico no prompt)

```bash
.venv/bin/python -m src.run historia --dry-run
cat state/workflow.json
# → tipo, fluxo, inputs, bloqueios, metadados de docs (sem texto bruto)
```

### 10. Prompt-less → Devin CLI → close_loop

A pipeline **gera** o contexto curto; o [Devin CLI](https://docs.devin.ai/) **implementa** num checkout isolado; o `DevinAdapter` grava evidência e o `close_loop` verifica. Não aponte o Devin para `inputs/` brutos — só para `outputs/` / `docs/prompt-less/`.

```
inputs/ (Figma, regras, engenharia, docs)
        │
        ▼
   Prompt-less (compressão + artefatos)
        │
        ▼
  docs/prompt-less/ no repo do app (workspace isolado)
        │
        ▼
   DevinAdapter → CLI → commit → execution.json + adapter-log.jsonl
        │
        ▼
   close_loop → runs/<id>/validations/verify-report.json
        │
        ▼
   src.approval request-approval → approve → promote (selo)
```

**Script incluso**

```bash
chmod +x scripts/devin-from-promptless.sh

# Gera historia+PRD, copia, roda DevinAdapter + close_loop
./scripts/devin-from-promptless.sh /caminho/do/seu-bff \
  --spec outputs/canonical-spec.yaml --layer bff

# Também gera OpenAPI + Mermaid
./scripts/devin-from-promptless.sh /caminho/do/seu-bff --full --layer bff

# Só prepara docs/prompt-less/ (sem Devin / sem close_loop)
./scripts/devin-from-promptless.sh /caminho/do/seu-bff --dry-prep

# Pasta com TODOS os repos: escaneia → mapa → marcadores → um pacote por repo
./scripts/devin-from-promptless.sh --workspace ~/dev/repos --dry-prep
```

Flags úteis: `--run-id`, `--spec`, `--layer`, `--no-close-loop`, `--timeout`.

O script grava em `APP/docs/prompt-less/`:

| Arquivo | Papel |
|---------|--------|
| `PRD.md` / `historia.md` | Fonte da verdade (RF/AC/NFR) |
| `openapi.yaml` / `sequence.mmd` | Contrato e fluxo (se `--full` ou já existirem) |
| `engenharia.yaml` | Stack + baseline NFR v1 |
| `DEVIN_PROMPT.md` | Prompt enxuto passado ao adapter |

**CLI direto**

```bash
PYTHONPATH=. .venv/bin/python -m src.executors.devin \
  --repo /caminho/do/seu-bff \
  --spec runs/<id>/artifacts/canonical-spec.yaml \
  --layer bff --run-id <id> --close-loop
```

Aprovação humana **não** usa `close_loop --approve`:

```bash
.venv/bin/python -m src.approval request-approval --root . --run-id <id>
.venv/bin/python -m src.approval approve --root . --run-id <id> \
  --actor alice --justification "…"
.venv/bin/python -m src.approval promote --root . --run-id <id>
```

E2E opcional (skip no CI sem credencial): `DEVIN_E2E=1 pytest -q tests/integration/test_devin_adapter.py`.

Instalação do CLI: `curl -fsSL https://cli.devin.ai/install.sh | bash`  
Handoff cloud: `/handoff` ([docs](https://docs.devin.ai/work-with-devin/devin-cli)).

### 11. Microsserviços — como a pipeline descobre o serviço

Com um txt longo **sem** mapa, ela **não** sabe o MS. Com `inputs/mapa-servicos.yaml`:

1. **Marcadores** no texto: `## Serviço: ms-cliente`, `[[service:ms-pagamento]]`, `<!-- service: ms-cliente -->`
2. **Keywords** do mapa nos chunks sem marcador (score)
3. Emite **um pacote por serviço** em `outputs/contextos/<id>/`

```bash
# Um serviço
.venv/bin/python -m src.run historia --context ms-cliente

# Todos os serviços com texto classificado
.venv/bin/python -m src.run historia --all-contexts
# → outputs/contextos/ms-cliente/{historia.md,PRD.md}
# → outputs/contextos/ms-pagamento/{historia.md,PRD.md}

# Ignorar mapa (legado: um artefato só)
.venv/bin/python -m src.run historia --no-split
```

Amostra: `inputs/amostra_microservicos.txt` + `inputs/mapa-servicos.yaml`.

Devin por repo dono:

```bash
./scripts/devin-from-promptless.sh ../bff-cliente --context ms-cliente --dry-prep
./scripts/devin-from-promptless.sh ../ms-pagamento --context ms-pagamento --dry-prep
```

### 12. De/para automático: pasta de repos → mapa → marcadores

Se você já trabalha numa pasta com **todos os repositórios** (padrão de uso do Devin CLI), não precisa escrever o `mapa-servicos.yaml` à mão. O `scripts/scan-repos.sh` deriva o mapa dos nomes dos repos e o `src/marcar.py` injeta os marcadores no texto de negócio.

```
~/dev/repos/                          inputs/mapa-servicos.yaml
├── gestao-de-ofertas-api    ─┐       gestao-de-ofertas:
├── gestao-de-ofertas-bff     ├──►      repos: [4 repos]
├── gestao-de-ofertas-mfe     │         camadas: {api, bff, mfe, gtw}
├── ofertas-gtw              ─┘         keywords: [gestao-de-ofertas, gestao, ofertas, /ofertas]
├── cadastro-cliente-api     ─┐       cadastro-cliente:
└── cadastro-cliente-bff     ─┘         camadas: {api, bff}
```

**Como o nome do repo é lido**

1. Tokeniza por `-`/`_`/`.` e separa **camada** (`api`, `gtw`, `gateway`, `bff`, `mfe`, `ms`, `svc`, `worker`, `batch`, `orq`, `web`, `front`) do resto
2. O resto vira a **jornada** → `service_id` (ex.: `gestao-de-ofertas`)
3. Jornadas contidas em outra são **fundidas**: `ofertas-gtw` entra em `gestao-de-ofertas` e `ofertas` fica como keyword/alias (desligue com `--no-merge`)
4. `keywords` = slug + tokens significativos (sem `de`/`da`/`para`…) + `/ultimo-token` para casar rotas no texto

**Injeção dos marcadores (de/para)**

`src/marcar.py` corta o doc **por seção** (títulos `## …`, `2.`, `2.1)`, `SEÇÃO …`), pontua cada seção com as keywords do mapa e escreve `[[service:<id>]]` na primeira linha da seção vencedora.

```bash
./scripts/scan-repos.sh --workspace ~/dev/repos      # gera o mapa (--dry-run p/ só ver)
.venv/bin/python -m src.marcar                        # de/para em dry-run + relatório
.venv/bin/python -m src.marcar --apply                # escreve os marcadores (.bak ao lado)
.venv/bin/python -m src.run historia --all-contexts
```

O relatório `outputs/marcadores_report.json` mostra a decisão seção por seção, para revisar antes de aplicar:

```json
"de_para": [
  { "secao": "2. Gestão de ofertas",   "servico": "gestao-de-ofertas", "score": 6 },
  { "secao": "3. Cadastro de cliente", "servico": "cadastro-cliente",  "score": 9 },
  { "secao": "5. Telemetria",          "servico": "_unassigned",       "score": 0 }
]
```

Detalhes de comportamento:

- **Idempotente**: marcadores gerados antes são removidos e recalculados; rodar 3× dá o mesmo arquivo
- **Marcador manual manda**: `## Serviço: x` escrito por você é preservado e vira o serviço corrente
- **Empate/ruído**: suba o corte com `--min-score 3` para deixar seções genéricas como `_unassigned`
- **`.docx`/`.doc`**: não são editados. Com `--apply --convert-binarios` a pipeline gera `<nome>.marcado.md` e renomeia o original para `.bak` (evita ingestão duplicada)

**Tudo de uma vez, com o Devin**

```bash
# escaneia repos → marca docs → gera por serviço → docs/prompt-less em CADA repo
./scripts/devin-from-promptless.sh --workspace ~/dev/repos --dry-prep

# um serviço só, e já chamando o devin em cada repo dele
./scripts/devin-from-promptless.sh --workspace ~/dev/repos --context gestao-de-ofertas
```

Cada repo recebe um `DEVIN_PROMPT.md` **escopado pela camada** — o `-api` é instruído a implementar só a API, o `-mfe` só o front — com o resto do serviço declarado como fora de escopo. Use `--no-scan` para reaproveitar o mapa atual e `--no-marcar` para não tocar nos docs.

### 13. Índice do código: assertividade sem LLM (`src/repo_index.py`)

O nome do repositório é um sinal pobre. Um documento pode falar de "vitrine", "cupom" e "carrinho" sem nunca escrever "ofertas" — e aí o de/para por nome de repo erra. O `repo_index` resolve isso lendo o **código real** e transformando-o em vocabulário.

```bash
.venv/bin/python -m src.repo_index --workspace ~/dev/repos   # → state/repo_index.json
.venv/bin/python -m src.repo_index --show gestao-de-ofertas  # evidência de um serviço
```

**O que é extraído** (regex estático, nada é executado):

| Sinal | Como | Exemplo real |
|-------|------|--------------|
| Rotas HTTP | Spring, Nest, Express, Fastify, FastAPI, Flask, Gin/Echo | `GET /v1/ofertas/ativas` |
| Rotas de spec | chaves sob `paths:` em OpenAPI/Swagger | `SPEC /gtw/ofertas/cupom` |
| Códigos HTTP | `HttpStatus.*`, `ResponseEntity.status()`, `status_code=`, `http.Status*` | `422`, `409` |
| Entidades | `class`/`interface`/`record`/`type … struct` | `Oferta`, `AplicarCupomDto` |
| Tabelas | `@Table(name=…)`, `CREATE TABLE` | `oferta_ativa` |
| Campos | atributos privados Java, campos tipados TS/Python | `percentualDesconto`, `cupom` |
| Stack | `pom.xml`, `build.gradle`, `package.json` (deps), `go.mod`… | `java/maven`, `nestjs` |
| Ponteiro (`evidencias`) | arquivo relativo, símbolo mais próximo, linha, rota, `confidence`, `origin` | `ClienteController.java:4` `POST /clientes` `observed` 0.90 |

A base da classe é concatenada com a do método, então `@RequestMapping("/v1/ofertas")` + `@GetMapping("/ativas")` sai como `GET /v1/ofertas/ativas`, e não como `/ativas` solto.

#### Como isso melhora o de/para

O `src.marcar` monta um vocabulário por serviço e pondera cada termo por **IDF**: o que aparece em vários serviços perde peso, o que é exclusivo de um ganha. Keyword de repo pesa `3.0`; termo de código pesa ~`1.0`. Acentos são normalizados, então "Gestão de Ofertas" casa com `gestao-de-ofertas`.

```bash
.venv/bin/python -m src.marcar --explain
```

Comparação na mesma amostra, uma seção intitulada **"Regras da vitrine e do cupom"**:

| Vocabulário | Decisão | Evidência |
|-------------|---------|-----------|
| Só nomes de repo | `_unassigned` (score 0) | — |
| Mapa + índice do código | `gestao-de-ofertas` (score 21.8) | `cupom×2`, `vitrine×2`, `segmento×1` |

Duas regras cortam o palpite silencioso, e cada seção não classificada declara o porquê:

| Regra | Flag | Motivo no relatório |
|-------|------|---------------------|
| Score mínimo | `--min-score` (2.0) | `sem_sinal` |
| Evidência mínima: 2 termos distintos, ou 1 repetido | `--min-terms` (2) | `sinal_isolado` |
| O 1º precisa superar o 2º em 1.3× | `--min-margin` (1.3) | `ambiguo_com_<servico>` |

Na prática: um `cpf` solto numa linha de log de telemetria não classifica a seção (`sinal_isolado`), e uma seção de visão geral que cita as três jornadas sai como `ambiguo_com_cadastro-cliente` em vez de ser atribuída à sorte.

#### Como isso melhora a história

`historia.md` e `PRD.md` renderizam **estado atual** e **gaps** a partir do
Canonical Spec (`current_state` / `gaps` / `code_evidence`), não de um placeholder.
Cada gap leva evidência (arquivo:linha, rota) ou marcação `[heurística]`.

```markdown
**Endpoints existentes** (1):
- `cadastro-cliente-api/src/.../ClienteController.java:4` `ClienteController` `POST /clientes/cadastro` _(observado, confiança 0.90)_

**Códigos HTTP já tratados:** `201`, `400`

### Gaps entre regra e código
- **GAP-001** [heurística] Regra `ERR-001` declara HTTP 401 … — _(sem ponteiro de arquivo; marcação heurística)_
```

Sem `state/repo_index.json` a seção declara *índice não aplicado* e **não** afirma
“sem gaps”. Método/path/status observados no código podem resolver campos do IR
com `origin: observed`; conflito com a regra declarada abre pergunta (`Q-nnn`).
O índice **não** entra no prompt — alimenta o IR e fica em `state/`, fora do budget.

#### Limites honestos

- É **léxico**, não semântico: sinônimo sem raiz comum ("desconto" vs "abatimento") não casa. Para isso seria preciso embeddings.
- Regex cobre os frameworks da tabela acima; stack fora dela (gRPC, GraphQL, serverless) ainda não é reconhecida.
- Repo grande é limitado a 4000 arquivos e 256 KB por arquivo, ignorando `node_modules`, `target`, `dist` e afins.
- O índice é um retrato: reindexe quando os repos mudarem (`--no-index` reaproveita o anterior).

---

## Engineering Harness

Além da geração de artefatos, a série 1 adicionou um **harness** auditável: cada run é isolada, o IR é validado antes do emit, e há CLIs para verify pós-executor, plano multi-repo e melhoria com gate de evals. Detalhe de releases: [CHANGELOG.md](./CHANGELOG.md).

### Runtime (`runs/<run_id>/`)

Cada `python -m src.run …` cria um diretório isolado e espelha artefatos em `outputs/` (compatível com scripts Devin).

| Caminho | Conteúdo |
|---------|----------|
| `runs/<id>/events.jsonl` | trilha append-only com cadeia HMAC (`prev_hmac` / `hmac`; `hash` é SHA-256 do payload) |
| `runs/<id>/manifest.json` | status versionado, objective, timestamps, `status_history`, `integrity` (selo HMAC-SHA256) |
| `runs/<id>/artifacts/` | artefatos da run (incl. `canonical-spec.yaml`) |
| `runs/<id>/artifacts/contextos/<svc>/` | pacotes por serviço (`--all-contexts`) |
| `runs/<id>/validations/` | `provenance.json`, `spec-validation.json` |
| `runs/<id>/validations/contextos/<svc>/` | `spec-validation.json` por serviço |
| `runs/<id>/state.json` | estado da execução (sem texto bruto) |
| `runs/<id>/checkpoints/` | um JSON por estágio (`schema_version`, hashes das entradas, status) |

**Contrato de contexto (único):** tudo que é por serviço vive em `contextos/<id>/` — na run (`artifacts/`, `validations/`) e no espelho (`outputs/contextos/<id>/`). O id do serviço é validado com a mesma regra do `run_id`.

### Storage seguro da run

`runs/` é o diretório autorizado da execução, e a pipeline trata isso como fronteira de segurança:

| Garantia | Como |
|----------|------|
| `run_id` canônico | `[A-Za-z0-9_][A-Za-z0-9_-]*` até 64 chars; `..`, `/`, `\`, espaço, ponto e `latest` são `InvalidRunId` |
| Sem escape de diretório | `run_dir.resolve()` precisa ficar sob `<root>/runs` (pega até symlink plantado) → `UnsafeRunPath` |
| Sem JSON parcial | manifest, `state.json`, `provenance.json`, `latest.json`, `canonical-spec.yaml` e pacotes LLM usam write-temp + `os.replace` (`src/runtime/atomic_io.py`); `emit` também |
| Integridade da trilha | cada evento em `events.jsonl` encadeia `prev_hmac` → `hmac` (HMAC-SHA256 de `kid:prev_hmac:hash`). Assinatura usa `PROMPTLESS_INTEGRITY_KEY` + `PROMPTLESS_INTEGRITY_KID` (default `v1`). Rotação: `PROMPTLESS_INTEGRITY_KEYS=v1=antiga`. Fail-closed se a chave atual faltar. `seal_artifacts()` roda **depois** de `finish`, sem emitir evento após o selo — `events_tip` é o HMAC de `run_finished`. `verify_run_dir` recusa ponta errada, kid desconhecido, evento forjado e artefato adulterado |
| Colisão de id | `bootstrap()` cria o diretório com `mkdir` exclusivo; id repetido = `RunIdCollision` (retomada explícita: `bootstrap(resume=True)`) |
| Transição de status | `set_status` valida a transição e usa `version` monotônica; escrita com versão obsoleta = `RunStateConflict`; estado terminal não reabre |
| Espelho publicado por manifesto | `outputs/.mirror-manifest.json` (run_id + sha256 por arquivo) é o ponto de commit; obsoletos da publicação anterior são removidos depois, symlinks são ignorados e arquivos nunca publicados nunca são apagados |

O espelho em `outputs/` é **last-writer-wins** por design (compatibilidade com os scripts Devin); a fonte da verdade auditável continua sendo `runs/<id>/`.

### Orquestração declarativa (`pipeline.yaml`)

`stages:` deixou de ser uma lista documental. Cada item vira um nó do grafo:

| Campo | Papel |
|-------|--------|
| `id` / `handler` | nome estável + função no registry (`src/runtime/handlers.py`) |
| `depends_on` | arestas do DAG (ciclo ou handler ausente = falha na carga) |
| `optional: true` | pulado no grafo default (`repos_scan`, `repo_index`, `marcar`) |
| `foreach: context` | corre uma vez por serviço depois de `servicos_split` |
| `gates` | lookup pontilhado fail-closed (ex.: `validation.has_errors` → `blocked`) |
| `retry` / `timeout_s` | tentativas extras e teto por estágio (omitidos = 0 / sem teto) |

Estágios são **idempotentes**: repetir o mesmo estágio na mesma run só regrava os mesmos artefatos. Checkpoints usam `schema_version: 1`. Retomar uma run antiga sem `checkpoints/` reconstrói a partir de `events.jsonl`.

```bash
.venv/bin/python -m src.run historia --dry-run --run-id run-manual-1
.venv/bin/python -m src.run historia --dry-run --run-id run-manual-1 --resume
```

`--resume` exige `--run-id`, recusa hashes de `inputs/` diferentes do checkpoint e só reabre runs `failed` / `cancelled` / `running`. Cancelamento (Ctrl+C) deixa `manifest.status: cancelled`. Handlers só escrevem dentro de `runs/<id>/` (`UnsafePath` se tentarem escapar). Backend continua **arquivo**; Redis não entra neste ticket.

### Provenance e claims

Na compressão RAG, trechos viram **claims** com `SourceRef` (arquivo, linhas selecionadas, `locator` JSONPath quando não há linha, hash). Há **um** identificador público: `id` (`CLM-0001`, `CLM-R001`, `CLM-SYN-001`). Em `--all-contexts` o mesmo `id` pode repetir; a chave é o par `(context, id)`. Não existe `uid`. `resolve_claim` é fail-closed se o `id` for ambíguo sem contexto. Referência explícita: `ms-cliente:CLM-0001`. Leitura ainda aceita o formato namespaced residual `CLM-ms-cliente-0001`. Claims sem fonte válida falham o gate (`CLAIM_WITHOUT_SOURCE` / `CLAIM_SOURCE_INVALID`).

Agregação multi-contexto (`--all-contexts`) deduplica por **identidade completa** (`context`, texto, origin, `service_id`, `chunk_id`, sources), não só por `claim.id`. O `provenance.json` inclui `spec.claims` (sintéticos `CLM-SYN-*` inclusive). `claim_links` no spec carrega `context` além de `claim_id`. Campos extras (`hmac`, `kid`, `integrity`) são aditivos. Descarte é reportado no mesmo arquivo. Runs bloqueadas pelo quality gate **preservam** `claims` e `discarded` no payload JSON.

Vínculo claim → RF/AC/erro é um `ClaimLink` (`method`, `score`, `requires_review`). Matching lexical com score < 0.6 emite warning `LOW_CONFIDENCE_CLAIM_MATCH` e marca revisão **sem** mudar o `status` do requisito (`max_unreviewed_inferences` nos evals continua contando só `ResolvedInt`). História e PRD listam os claims utilizados na seção **Proveniência**.

### Canonical Spec + quality gate

Antes de renderizar história/PRD, a pipeline monta o IR (`src/spec/builder.py`) e valida (`src/validators/`):

- ambiguidade de status HTTP → `PipelineBlocked` (não default silencioso para 422)
- defaults/inferências explícitos (`origin`, `confidence`, `requires_review`)
- `unexpected_inferences` conta ResolvedValues `default|inferred` sem review
- traceability de claim IDs (órfãos = warning)
- **evidência de código** (`current_state`, `gaps`, `code_evidence`): ponteiros do
  `repo_index` (arquivo, símbolo, linha, rota, confiança) com origem
  `observed` ou `heuristic` explícita; conflito regra × código vira pergunta aberta

Artefato: `canonical-spec.yaml` ao lado dos demais outputs da run.

### Artefatos derivados do IR (OpenAPI / Mermaid)

`openapi.yaml` e `sequence.mmd` são renderizados **do Canonical Spec**, a mesma
fonte da história e do PRD — os cinco artefatos não podem divergir.

```bash
.venv/bin/python -m src.run openapi --dry-run   # → outputs/openapi.yaml + canonical-spec.yaml
.venv/bin/python -m src.run mermaid --dry-run   # → outputs/sequence.mmd
```

O que o IR carrega para isso:

| Campo do IR | Efeito no artefato |
|---|---|
| `operations[].owner` / `service_id` | recorte do IR: cada spec só publica as ops do serviço |
| `operations[].method` / `path` | path item + método do OpenAPI e chamadas da sequência |
| `operations[].request_schema` / `response_schema` | `components.schemas.*` com `origin` por campo |
| `operations[].success_status` | resposta de sucesso **só** se `requires_review: false` |
| `operations[].unresolved` | `x-unresolved` / `x-unresolved-operations` e comentário `%%` no Mermaid |
| `errors` | respostas `4xx` + blocos `alt`, com `x-error-ids` e `x-source-claims` |

Antes de gravar, o artefato passa por dois gates (`src/validators/`):

1. **estrutural** — `openapi` 3.x, `info`, paths com `/`, operações com
   `operationId` e `responses`, `$ref` resolvível, parâmetro de path declarado
   e obrigatório
2. **anti-divergência** — status, path, operação, erro ou campo fora do IR é
   erro; sucesso `2xx` sem `success_status` resolvido é
   `ARTIFACT_RESOLVED_WITHOUT_EVIDENCE`; `unresolved` do IR omitido no artefato é
   `ARTIFACT_MISSING_UNRESOLVED_MARK`

Falha de gate **não** emite o arquivo: a run volta `status: blocked`,
`reason: derived_artifact_divergence` e grava
`runs/<id>/validations/<tipo>-validation.json`.

Sucesso sem evidência permanece `unresolved` de propósito: só vira `200`/`201`
quando as decisões declaram um único 2xx e existe uma única operação **com dono**
no spec (aí o `success_status` guarda `origin: declared` e os `source_claims`).

Com `--context <svc>` ou `--all-contexts`, o Canonical Spec é fatiado **no IR**:
`spec.operations` só contém as ações cujo `owner` é aquele serviço (e os `ERR-*`
ancorados nela). OpenAPI, Mermaid e o consumidor SDD leem o mesmo
conjunto — o renderer não adivinha fronteira de microsserviço. Operação sem dono
e erro órfão ficam `unresolved` (pergunta aberta não bloqueante) e **não** viram
path/status no contrato de outro serviço.

```bash
.venv/bin/python -m src.run openapi --context ms-cliente --dry-run
.venv/bin/python -m src.run openapi --all-contexts --dry-run
# → runs/<id>/artifacts/contextos/<svc>/canonical-spec.yaml + openapi.yaml
```

### Ciclo executor (`close_loop`)

Fecha o loop **evidência real × spec × policy de camada**. O payload do
executor é relato: `changed_files` sai de `git diff` entre `base_commit` e
`result_commit`, comandos vêm do JSONL estruturado do adapter, e cada teste
precisa de comando, `exit_code`, timestamp e artefato/log. Divergência entre
relato e evidência é erro (`EVIDENCE_DIVERGENCE`). O `verify-report.json`
inclui `evidence_hashes` (SHA-256 do diff, do log e dos artefatos de teste,
com HMAC reusando `PROMPTLESS_INTEGRITY_KEY`).

```bash
.venv/bin/python -m src.close_loop \
  --spec runs/<id>/artifacts/canonical-spec.yaml \
  --result tests/fixtures/executor/execution_ok.json \
  --repo path/para/checkout \
  --adapter-log path/adapter-log.jsonl \
  --out runs/<id>/validations

# tentativa de reparo (não promove)
.venv/bin/python -m src.close_loop --spec ... --result ... --repo ... --attempt 1 --layer bff
```

`--repo` e os commits são obrigatórios. Sem ancestralidade no mesmo
repositório, sem log do adapter ou com teste apenas “declarado”, o verify
falha fechado. `--approve` **não** marca mais `approved=True` — o comando
sai com erro e aponta para `src.approval`.

### Aprovação auditável (`src.approval`)

Pedido, decisão humana e promoção são comandos separados. O registro em
`runs/<id>/validations/approval.json` identifica **quem** aprovou **qual**
Canonical Spec, verify-report e `result_commit`. HMAC reusa
`PROMPTLESS_INTEGRITY_KEY` / `seal_hmac` do 19: adulterar o arquivo invalida
a promoção. Rejeição também é persistida (`approve --reject`). Aprovação de
uma run não vale em outra. Promote **não** aplica código (isso é o ticket 14).

```bash
.venv/bin/python -m src.approval request-approval --root . --run-id <id>
.venv/bin/python -m src.approval approve --root . --run-id <id> \
  --actor alice --justification "spec, diff e commit conferem" --origin cli
.venv/bin/python -m src.approval approve --root . --run-id <id> \
  --actor alice --justification "fora do combinado" --reject
.venv/bin/python -m src.approval promote --root . --run-id <id>
.venv/bin/python -m src.approval show --root . --run-id <id>
```

Mudar o spec, o verify-report (diff) ou o `result_commit` **expira** a
aprovação vigente. Promote sem registro válido e vinculado falha fechado.

Policy (`config/permission_profiles.yaml` + `src/executors/policy.py`):

- writes/comandos allow/deny por camada (`bff`, `api`, `mfe`, `gtw`, `worker`, `batch`)
- camada ausente no YAML → fail-closed (`UNKNOWN_EXECUTION_LAYER`)
- comandos parseados como argv (`shlex`); `&&` / `;` / `||` / backticks negam
- allowlist **semântica**: tokens exatos do executable + args; path extra passa por `realpath`/normalize
- paths: `normalize_repo_path` rejeita absoluto e `..`; com `repo_root`, symlink que escapa o repo é recusado
- policy avalia o **diff Git** e o **realpath** (symlink para `infra/prod` não passa só porque o path Git está em `src/`)
- execução nova vai por `src/executors/safe_exec.run_argv` — `shell=True` é erro
- verify fail-closed para layer desconhecido; `NO_TESTS_REPORTED` é error em code change
- `FILE_OUT_OF_SCOPE` → `required_reverts` (não amplia `editable_surface`)
- rastreio RF/AC precisa existir no `result_commit` (arquivo e linha)

O `close_loop` também grava `debugger.json` ao lado do `verify-report.json` (e a pipeline grava `runs/<id>/validations/debugger.json` em blocked/failed). Campos: `failure`, `agent_behavior`, `harness_component`, `root_cause`.

O adapter Devin (`src/executors/devin.py`) invoca o CLI, grava JSONL +
`execution.json` e exige worktree limpo vs `result_commit` antes do verify.
Metadados da sessão ficam em `devin-session.json` (fora do JSONL de policy).


### Apply + rollback (`src.apply`)

```bash
.venv/bin/python -m src.apply --root . --proposal-json /tmp/prop.json --cases happy_path
# risco medium+ exige run aprovada:
.venv/bin/python -m src.apply --root . --proposal-json /tmp/medium.json \
  --run-dir runs/<id> --run-id <id> --cases happy_path
```

Fluxo: gate de risco → snapshot de bytes em `state/knowledge/snapshots/<id>/` → aplica
`change.key/value` em arquivos versionados sob `config/` (YAML nomeado quando o prefixo
bate, senão `proposal-overlay.yaml`) → re-roda a eval suite com o cfg mesclado
(baseline pré-apply × candidate pós-apply) → regressão restaura bytes e marca
`rejected`; sem regressão mantém a mudança e registra `accepted` com
`applied_to_production`.

### Hardening (`src/hardening/`)

Camada de confiança da run, **antes** do `--live`:

| Peça | Onde | Efeito |
|---|---|---|
| Agent Debugger | `validations/debugger.json` | separa falha do executor, da spec e do harness |
| Scan de inputs | `validations/input-scan.json` | secrets / PII / injection; error = fail-closed |
| Recovery de claims | tools no `llm_package` | `search_claims(query, service_id?)`, `get_claim(claim_id)` |
| Golden recall | `tests/fixtures/golden/expected_claims.yaml` | o teste falha se o recall dos claims anotados cair |

Fora deste ticket: scan de dependência no CI (`25`), cadeia tamper-evident (`19`), clientes OpenAI/Claude (`09`).

### Plano multi-repo (`plan_repos`)

O plano usa **dependências observadas** (OpenAPI clients, imports, URLs, eventos, arquivos de build e contratos do Canonical Spec). Cada aresta tem `from`, `to`, tipo, arquivo/símbolo, confiança e o **motivo**. Topologia por camada permanece só como fallback `origin: heuristic` + `requires_review`. Ciclos, contratos ausentes e repositório compartilhado sem `coordenacao` bloqueiam o scheduler. `ready_for_parallel_execution` exige `--reviewed` e ausência de conflito.

```bash
.venv/bin/python -m src.plan_repos
.venv/bin/python -m src.plan_repos --service gestao-de-ofertas --out runs/plan/
.venv/bin/python -m src.plan_repos --workspace ~/dev/repos --spec runs/<id>/artifacts/canonical-spec.yaml --reviewed
# → implementation_plan.yaml + .json (dependencies, ondas, cycles, scheduler_blockers)
```

#### Execução por ondas (`parallel_exec`)

Com o plano revisado, o scheduler consome `waves` e roda até N adapters em paralelo
(semáforo configurável). Relatório agregado por repositório; falha numa task **não**
apaga os resultados das irmãs da mesma onda. O state em arquivo aceita
compare-and-set + lock (Redis continua parqueado em `12b`).

```bash
# inspeciona ondas sem executar
.venv/bin/python -m src.parallel_exec --plan runs/plan/implementation_plan.json --dry-run

# smoke do scheduler (runner stub; não chama Devin)
.venv/bin/python -m src.parallel_exec --plan runs/plan/implementation_plan.json \
  --stub --max-concurrency 2 --out runs/parallel/ --state state/parallel-exec.json
# → runs/parallel/parallel-report.json
```

Injeção de adapter real: `run_plan_waves(plan, adapter=…, max_concurrency=N)` em
`src.executors.scheduler` (ex.: wrapping do `DevinAdapter` do ticket `10`).

### Autoaperfeiçoamento (`improve`)

```bash
.venv/bin/python -m src.improve --verify-report /tmp/verify/verify-report.json
.venv/bin/python -m src.improve --out state/knowledge   # demo sem report (falha AMBIGUOUS_HTTP)
.venv/bin/python -m src.improve --cases happy_path,eval_adversarial --out /tmp/improve
```

Fluxo: diagnose (padrões em `failure-patterns.yaml`) → propostas limitadas (`playbook.yaml`) → **workspaces distintos** (snapshot de `config/` em `evals/workspaces/{baseline,candidate}`) → a proposta é aplicada **somente no candidato** (overlay atômico) → eval suite nos dois lados → decisão.

Status:

| Status | Significado |
|--------|-------------|
| `proposed` | proposta gerada, ainda sem apply |
| `applied_to_candidate` | overlay gravado só no workspace candidato |
| `evaluated` | evals baseline × candidate rodaram |
| `approved_for_experiment` | aplicada, sem regressão crítica; ainda não é melhoria comprovada |
| `accepted` | melhoria comprovada **no candidato** (não é apply em produção) |
| `rejected` | regressão crítica, não aplicada, risco medium+, ou workspaces iguais |

Uma proposta **não aplicada** nunca entra em `accepted` nem `approved_for_experiment`. Regressão em qualquer caso `critical: true` rejeita o candidato mesmo se o pass rate agregado subir. O gate HTTP das evals compara **contratos tipados por operação** (`http_operations` na fixture: serviço, método, rota, `success_status` resolvido e erros vinculados) — números em RF/AC/perguntas **não** provam o contrato; sucesso ausente/pendente (`requires_review`) não recebe valor presumido. Sem `http_operations`, o fallback `http_statuses` também só lê o tipado. Modo `exact` (default em `critical`) vs `subset` (`http_status_mode`) aplica-se aos erros da operação. O histórico (`state/knowledge/proposals-history.json`) guarda diff e métricas comparadas. Apply em produção continua no ticket `14`.

Limites deste slice (não reabrir; o `14` consome o overlay):

- O apply grava `config/proposal-overlay.yaml` só no candidato. `src.run` continua lendo `config/pipeline.yaml` do ROOT — a eval prova isolamento e gates, não o efeito da chave do playbook no IR.
- A suíte default inclui `eval_adversarial` e `eval_multi_context`. `--cases` restringe.

### Evals e testes

```bash
# Gate completo (igual ao GitHub Actions). pytest sozinho não é o CI.
PYTHONPATH=. .venv/bin/python scripts/quality_gates.py
```

Fixtures em `tests/fixtures/` (happy_path, access_denied, ambiguous_status, two_services, **eval_adversarial**, **eval_multi_context**), goldens de artefato derivado e de **recall de claims** em `tests/fixtures/golden/`, e casos adversariais (`adversarial_injection`, `adversarial_secret`). Scoring por camada: `ingestion` / `canonical_spec` / `artifacts` / `provenance`, com métricas de claim recall, traceability, inferências inesperadas, custo e latência. O gate HTTP usa `http_operations` (serviço + método + rota + sucesso tipado + erros da op); casos `critical` têm gate individual na comparação baseline × candidate. CI em `.github/workflows/ci.yml` (gates de produção: compile, lint, types, coverage, audit, secrets, YAML, artifacts).


---

## Estrutura do repositório

```
pipeline/
├── README.md
├── CHANGELOG.md
├── pyproject.toml                 # ruff, mypy, coverage (piso 70%)
├── requirements.in / requirements-dev.in
├── requirements.lock / requirements-dev.lock
├── requirements.txt               # piso não pinado (aponta o lock)
├── pytest.ini
├── .secrets.baseline
├── .yamllint.yaml
├── .github/workflows/ci.yml
├── scripts/
│   ├── ci_reports.py              # YAML + artifacts eval/coverage/verify
│   ├── scan-repos.sh              # pasta de repos → mapa-servicos.yaml (de/para)
│   └── devin-from-promptless.sh   # scan + index + marcar + artefatos → Devin CLI
├── config/
│   ├── pipeline.yaml              # budget, stages (grafo real), caching, artefatos
│   ├── tools.compact.yaml         # tools sem prosa
│   ├── permission_profiles.yaml   # policy por camada (write/command allow-deny)
│   ├── playbook.yaml              # propostas de melhoria limitadas
│   └── failure-patterns.yaml      # classificação de falhas no improve
├── prompts/
│   └── system.compact.txt
├── templates/
│   ├── openapi.skeleton.yaml
│   ├── mermaid.skeleton.md
│   ├── historia.skeleton.md
│   └── prd.skeleton.md
├── inputs/                        # figma, regras, engenharia, mapa-servicos, docs
├── state/                         # workflow legado + repo_index + knowledge/
├── runs/                          # execuções isoladas por run_id
├── outputs/                       # espelho compatível (Devin/scripts)
├── docs/
│   └── rag-e-cli.md
├── tests/
│   ├── fixtures/                  # evals + executor samples
│   └── integration/
└── src/
    ├── apply.py                   # apply em config + snapshot/rollback
    ├── run.py                     # pipeline + Canonical Spec + runtime
    ├── close_loop.py              # verify por evidência (Git + logs) / repair
    ├── parallel_exec.py           # scheduler CLI: ondas + semáforo + relatório
    ├── approval.py                # request-approval / approve / promote (HMAC)
    ├── plan_repos.py              # implementation_plan multi-repo
    ├── improve.py                 # diagnose → propose → eval → gate
    ├── ingest.py / docs_ingest.py / preprocess.py / engenharia.py
    ├── servicos.py / marcar.py / repo_index.py
    ├── state_store.py             # workflow state + CAS/lock (file; redis=12b)
    ├── doc_compress.py / rag_compress.py
    ├── context_builder.py / reason.py / emit.py / economia.py
    ├── domain/                    # Claim, SourceRef, DocumentChunk, CanonicalSpec
    ├── runtime/                   # RunContext, RunStore, EventStore, atomic_io, approval
    ├── spec/                      # builder do IR
    ├── validators/                # quality gate
    ├── renderers/                 # história/PRD/OpenAPI/Mermaid/SDD a partir do IR
    ├── executors/                 # policy, verify, evidence, loop, Devin, scheduler, safe_exec
    ├── hardening/                 # debugger, input scan, claim tools, recall
    ├── planning/                  # grafo observado, camadas (fallback), plan
    └── learning/                  # evals, proposals, accept, failure_patterns
```

Leitura recomendada: `run.py` → `spec/builder.py` → `validators/` → `executors/verify.py` → `learning/evals.py`. Para o caminho clássico de tokens: `rag_compress.py` → `doc_compress.py` → `context_builder.py`.

---

## Configuração (`config/pipeline.yaml`)

Parâmetros principais de budget:

| Chave | Default | Efeito |
|-------|---------|--------|
| `max_context_tokens` | 2000 | Teto do contexto montado |
| `target_context_tokens` | 650 | Alvo operacional (estilo artigo) |
| `consolidated_summary_max_tokens` | 200 | Tamanho do consolidado RAG/docs |
| `rag_chunk_max_tokens` | 120 | Influencia tamanho do resumo por chunk |
| `doc_lines_per_chunk` | 40 | Granularidade do fatiamento de docs |
| `models.provider` | `openai` | Estratégia de tokenizer (`openai` / `anthropic` / `google`) |
| `models.name` | `gpt-4o` | Modelo cuja encoding oficial é usada (OpenAI → tiktoken) |

Artefatos e encadeamento:

```yaml
artifacts:
  historia:
    template: templates/historia.skeleton.md
    output: outputs/historia.md
    also_emit: [prd, sdd]     # mesma run → PRD.md + sdd-package.yaml
  prd:
    template: templates/prd.skeleton.md
    output: outputs/PRD.md
    also_emit: [sdd]
  sdd:
    template: templates/sdd.skeleton.yaml
    output: outputs/sdd-package.yaml
```

Ajuste o budget conforme o provedor (janela, preço de cache) e o risco de “cortar demais” sinais.

Estágios (trecho do grafo default):

```yaml
stages:
  - id: canonical_spec
    handler: canonical_spec
    depends_on: [rag_compress]
    foreach: context
    gates:
      - when: validation.has_errors
        then: blocked
  - id: emit
    handler: emit
    depends_on: [reason]
    foreach: context
```

---

## Dependências

- **Python 3.10–3.13** — a matriz do CI cobre exatamente essas versões
- Runtime: `PyYAML`, `python-docx` (`.docx`), `tiktoken` (tokenizer OpenAI; sem ele, fallback heurístico) — lock em `requirements.lock`
- Dev/CI: `pytest`, `ruff`, `mypy`, `coverage`, `pip-audit`, `detect-secrets`, `yamllint` — lock em `requirements-dev.lock`
- macOS: `textutil` nativo para `.doc` legado  
  Linux: `antiword` (opcional) para `.doc`

Instalação reproduzível:

```bash
python -m pip install --require-hashes -r requirements-dev.lock
```

`requirements.txt` continua sendo o piso não pinado (`PyYAML` / `python-docx` / `pytest`) para um `pip install` rápido. O CI **não** usa esse arquivo — usa o lock com hashes.

---

## Gates de qualidade

Local e GitHub rodam **o mesmo comando**: `python scripts/quality_gates.py`
(compile, ruff, mypy, YAML, secrets, pip-audit, pytest+coverage 70%, smoke).
`pytest -q` sozinho **não** é o gate — foi isso que fez cada onda voltar a
falhar no mypy depois do push. Antes de merge no pai / push de
`feature/onda-frontier`, rode o script. Não silencie módulo novo em
`pyproject.toml` `[tool.mypy.overrides]`.

O job agregador **`CI`** (depende de `quality-gates` na matriz) é o check estável para exigir no GitHub. Cada célula da matriz publica o artifact `quality-reports-py<versão>` com:

| Arquivo | Origem |
|---------|--------|
| `coverage.xml` / `coverage.json` / `coverage-html/` | pytest-cov (`--cov-fail-under=70`) |
| `coverage-by-module.json` | cobertura por arquivo (não só o agregado) |
| `eval-report.json` | resumo do junit, ou placeholder se a run não gerou eval |
| `verify-report.json` | placeholder `ci_no_close_loop` quando o workflow não roda `close_loop` |
| `pytest.xml` | junit da suíte (inclui testes adversariais) |

`pip-audit --strict` faz parte do gate. O lock é compilado em Python 3.10 (`pip>=26.2`, `setuptools>=83`, `exceptiongroup` para o pytest 9) e a matriz cobre 3.10–3.13, para que os fixes de CVE que largaram o 3.9 entrem no gate sem `--ignore-vuln`.

### Branch protection (ainda não ativa)

Em 2026-09-18 a API (`gh api repos/ilaraca/prompt-less/branches/main`) respondeu `protected: false`. A permissão de admin existe, mas **não** ligamos a regra agora: o check `CI` só passa a existir no remoto depois deste workflow chegar em `main`; exigí-lo antes bloquearia merges.

Depois do merge em `main`, em **Settings → Branches → Add branch protection rule** (`main`):

1. Require a pull request before merging
2. Require approvals: **1**
3. Require status checks to pass before merging → check **`CI`**
4. Require branches to be up to date before merging
5. Não marcar “Allow bypassing” para administradores se quiser o gate inescapável

Equivalente via API (quando for a hora):

```bash
gh api -X PUT repos/ilaraca/prompt-less/branches/main/protection \
  -F required_status_checks.strict=true \
  -F 'required_status_checks.contexts[]=CI' \
  -F enforce_admins=true \
  -F required_pull_request_reviews.required_approving_review_count=1 \
  -F restrictions= \
  -F required_linear_history=false
```

Até essa regra existir, merge em `main` **não** está protegido pelo GitHub — só pelo workflow que falha na PR.

---

## Métricas e observabilidade

Cada execução imprime JSON com:

- `output` / `outputs` — caminho principal e mapa de todos os arquivos emitidos (ex.: `historia` + `prd`)
- `llm_package` / `llm_packages` — pacotes por tipo
- `est_tokens` — estimativa do pacote principal (tokenizer oficial ou heurística)
- `est_tokens_method` — `official` ou `heuristic`
- `token_usage` — `estimated`, `method`, `billable`/`delta` (preenchidos no live / 09)
- `rag.raw` / `rag.compressed` — antes/depois da compressão
- `rag.doc_reduction_pct` — % de redução documental
- `docs_ingested` — lista de arquivos e linhas

Use essas métricas para validar que a pipeline continua “barata” ao crescer o volume de insumos.

### Calculadora de economia (`src/economia.py`)

Mede o custo estimado de gerar o mesmo artefato de **duas formas** e mostra a diferença em tokens e USD.

#### O que é “naive”?

**Naive** (do inglês *ingênuo*) é o **cenário-baseline**: usar o LLM “do jeito mais direto”, **sem** as técnicas do Prompt-less. É o contraste da calculadora — não um modo da pipeline.

Na prática, é o que acontece quando alguém cola tudo no chat/agente:

| Componente | O que o cenário naive assume |
|------------|------------------------------|
| Documentos | Texto **inteiro** de `inputs/` (ex.: txt de 3000 linhas) vai no prompt |
| Figma / regras / engenharia | JSON/YAML **brutos**, sem desidratar |
| System prompt | Longo e repetido a cada turno (~2,5k tokens) |
| Tools | Definições verbosas (~1,8k tokens) |
| Histórico | Conversa acumulada no contexto (~3k tokens) |
| Cache | Baixo aproveitamento (prefixo muda com o histórico) |

Ou seja: **naive = “manda tudo pro modelo”**. Não há compressão hierárquica, state externo, system compacto nem budget.

O **Prompt-less** é o outro lado da conta: só o consolidado + state mínimo + system/tools curtos, **sem** histórico e **sem** texto bruto.

```
naive:        [system longo][tools longas][histórico][docs 3000 linhas][figma bruto]…
                 └───────────── dezenas de milhares de tokens ─────────────┘

prompt-less:  [system curto][tools curtas][state][consolidado ≤ budget][template]
                 └───────────── ~1k tokens ─────────────┘
```

A calculadora **não executa** o cenário naive de verdade — ela **estima** quantos tokens ele gastaria com os mesmos insumos, para você ver a economia.

```bash
# Mede os inputs/ atuais (default: gpt-4o, 40 runs/mês, historia+prd)
.venv/bin/python -m src.economia

# Outro modelo / volume
.venv/bin/python -m src.economia --modelo claude-sonnet --runs-mes 80

# Comparativo entre modelos
.venv/bin/python -m src.economia --comparar

# Cenário hipotético (doc de 3000 linhas, sem ler inputs/)
.venv/bin/python -m src.economia --what-if --linhas 3000 --runs-mes 40

# JSON para CI/dashboard
.venv/bin/python -m src.economia --json
.venv/bin/python -m src.economia --listar-modelos
```

Na amostra incluída (~3000 linhas + microserviços + docx), a calculadora típica reporta **~98% menos tokens de input** e dezenas de dólares/ano mesmo em volume baixo — o salto cresce linearmente com `runs-mes` e com o tamanho dos docs.

| Flag | Papel |
|------|--------|
| `--modelo` | `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `claude-sonnet`, `claude-haiku`, `gemini-flash` |
| `--runs-mes` | quantas execuções da pipeline por mês |
| `--artefatos` | chamadas LLM por run (default 2 = história + PRD) |
| `--cache-hit` | fração do prefixo estável lida do cache (0–1) |
| `--output-tokens` | tokens estimados da completion |
| `--what-if --linhas N` | simula sem depender dos arquivos em `inputs/` |

**Contagem naive (baseline):** docs brutos + figma/regras/engenharia/template + ~2,5k system + ~1,8k tools + ~3k histórico.  
**Contagem Prompt-less:** pacote de `build_context` (system compacto + state + consolidado + template) + tools compactas — **sem** histórico e **sem** texto bruto.

Preços são tabelas de referência (USD / 1M tokens). Atualize `MODELOS` em `src/economia.py` se o vendor mudar a lista. A contagem pré-chamada usa o tokenizer do `--modelo` (`method=official` via tiktoken no OpenAI). Sem a lib oficial, ou em Anthropic/Gemini, o fallback é `chars÷4` com `method=heuristic` e **não** é apresentado como contagem exata. No `--live`, `token_usage.billable` / `delta` / `cache_hit` vêm da resposta do vendor (`observe_billable`).

---

## Limitações atuais e próximos passos

**Limitações** (riscos residuais Onda C–E aceitos em 2026-09-18 — ver board)

- `--live` cobre OpenAI Responses e Claude Messages (HTTP stdlib); Google Gemini
  ainda não tem client; loop de tools de recovery é limitado a poucas rodadas;
  IDs Anthropic curtos mapeiam para snapshot pinned; `cost_usd` usa tabela local
  (`economia.MODELOS`), não a fatura do vendor; artefato live ainda passa pelo
  gate `derived_artifact` (saída fora do IR bloqueia — intencional) (`09`)
- Devin E2E (`10`): o adapter não captura automaticamente os comandos internos
  da sessão Devin — testes/build precisam constar no sidecar
  `docs/prompt-less/execution-result.json` (ou JSONL) com artefato/log; sem
  isso o verify falha fechado em code change (`NO_TESTS_REPORTED` /
  `TEST_NOT_EVIDENCED`)
- `DEVIN_E2E=1` exige CLI Devin autenticado e rede; no CI sem credencial o
  teste live é skip (`10`)
- Auto-commit do adapter fica só no checkout isolado — sem push nem abertura
  de PR pelo harness (`10`)
- Sem `PROMPTLESS_INTEGRITY_KEY`, `evidence_hashes.hmac` fica nulo (SHA-256
  permanece) — **aceito**; selo tamper-evident da aprovação é o `21`
- `improve` aplica propostas só no workspace candidato; `python -m src.apply`
  promove config versionada com snapshot/rollback (`14`). Overlay/keys ainda sem
  consumidor completo de negócio no IR (persistência + anti-regressão). Jitter de
  `avg_latency_ms` sozinho não prova melhoria. `promote` continua só selo.
  Sem `--cases`, a suíte default de apply é a completa (custo alto)
- Recuperação híbrida: 2ª camada semântica = sinônimos locais + TF (não
  embeddings); `doc_preface` CLI permanece navegação do agente, não estágio (`26`)
- OpenAPI/Mermaid derivam do IR já fatiado por `owner`: `--all-contexts` não
  replica a action de um serviço no contrato de outro; operação sem dono e
  erro órfão ficam `unresolved`
- Status de sucesso só é resolvido com evidência: um 2xx declarado inequívoco
  (uma operação + um 2xx nas decisões) **ou** um 2xx único observado no código
  na rota casada (`origin: observed`); fora disso permanece `unresolved`
- Sem `repo_index`, história/PRD declaram *índice não aplicado* e não afirmam
  “sem gaps”; heurística nunca é apresentada como fato
- Plano multi-repo sem evidência de código cai na topologia por camada
  (`origin: heuristic`, exige revisão); o scheduler de ondas (`13`) já roda com
  adapter injetável / `--stub` — wiring Devin-por-task no CLI ainda é manual
- Scheduler (`13`): falha parcial numa onda **não** aborta o plano — a onda
  seguinte ainda roda; só isola o resultado da task. Wiring Devin-por-task no
  CLI continua via adapter injetado / handoff do `10`
- O pacote SDD lê o grafo multi-repo observado quando há evidência; fallback
  heurístico continua `requires_review`. NFRs são selecionados por camada +
  criticidade (`28`); tasks recebem o subconjunto da sua `layer`
- Sinais de NFR no índice (CircuitBreaker, MeterRegistry, OTel…) são heurísticos
  por substring — falso positivo/negativo possível; gap `GAP-NFR-*` marca origem
  `heuristic` quando o baseline exige e o código não mostra sinal (`28`)
- Alertas/ADRs/bulkhead ainda não entram no catálogo v2
- Tasks do SDD usam o grafo de ondas no pacote; despacho Devin automático por
  task no CLI de `parallel_exec` ainda exige adapter injetado (não o stub)
- Resumo de docs é **extrativo por regex**, não LLM small (bom custo; pode perder nuance)
- Tokenizer oficial cobre OpenAI via `tiktoken`; Anthropic/Gemini e ausência da lib usam heurística `chars÷4` (`method=heuristic`), nunca como contagem exata
- State backend: **arquivo** com compare-and-set/lock (`13`); `redis` previsto no
  YAML permanece parqueado (`12b`)
- Branch protection em `main` **não** está ligada no GitHub (ver [Gates de qualidade](#gates-de-qualidade)); o workflow já é required-ready
- Timeout de estágio é best-effort (thread); o handler pode continuar em background após o teto
- Estágios opcionais (`repos_scan`, `repo_index`, `marcar`) existem no YAML mas ficam desligados no default
- Scan de inputs é heurístico (regex); não substitui secret manager nem DLP
- PII de baixa confiança (e-mail/telefone) só registra warning — não bloqueia sozinha

**Próximos passos (série 2 — ver CHANGELOG [Unreleased])**

1. Redis opcional (state backend) (`12b`) — CAS/lock no file já entregue no `13`
2. Wiring Devin-por-task no CLI de `parallel_exec` (além de `--stub` / adapter injetado)
3. Client `--live` para Gemini / endurecer o agent loop de tools
4. Embeddings opcionais na 2ª camada de retrieval (hoje sinônimos locais)
5. Alertas / ADRs / bulkhead no catálogo de engenharia (extensão do `28`)
6. Ligar estágios opcionais de scan/index/marcar no grafo default


---

## Lição de design

> Sistemas LLM em produção funcionam melhor quando o modelo vê a **informação certa**, não a **maior quantidade** de informação.

O **Prompt-less** aplica isso ao domínio de artefatos de tech lead: Figma, regras, engenharia e documentos longos viram um contexto pequeno, estável e auditável — pronto para gerar OpenAPI, Mermaid, histórias (**funcional + NFR**), **PRD** e **pacote SDD** com custo previsível, com harness (runtime, provenance, Canonical Spec, verify) entre o sinal comprimido e a implementação.
