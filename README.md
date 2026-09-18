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
- baseline de engenharia (**stack + NFR v1**: timeout/retry + logs + README/changelog/Javadoc) via `inputs/engenharia.yaml`;
- **harness**: runtime por `run_id`, provenance/claims, Canonical Spec + quality gate, ciclo verify/repair, plano multi-repo e melhoria com evals (sem apply automático).

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
| **Verify pós-executor** | `close_loop` confere ExecutionResult vs spec + policy de camada |
| **Plano coordenado multi-repo** | `plan_repos` gera ondas/contratos a partir do mapa de serviços |
| **Melhoria sem regressão silenciosa** | `improve` + evals; propostas só `approved_for_experiment` |

### Onde *não* é a melhor ferramenta (ainda)

| Cenário | Motivo |
|--------|--------|
| Geração 100% automática em produção sem revisão humana | Dry-run preenche esqueleto; `--live` (API) ainda é slot a plugar; Devin E2E e apply+rollback são série 2 |
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
                            openapi | sequence.mmd | historia.md | PRD.md | canonical-spec.yaml

        (pós-execução, opcional)
 [close_loop] ───────────── ExecutionResult × spec × policy → verify / repair
 [plan_repos] ───────────── mapa-servicos → implementation_plan (ondas)
 [improve] ──────────────── diagnose → propostas → evals → approved_for_experiment
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

A orquestração está em `src/run.py`. Cada etapa tem um módulo próprio; o dado flui **sempre desidratando** — o que sobra no final é o mínimo necessário para gerar o artefato.

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
| **Generate** | Montar pacote LLM / dry-run scaffold / (futuro) chamada `--live` |

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
| Embeddings (OpenAI, sentence-transformers, etc.) | Não |
| Vector DB (Chroma, Pinecone, pgvector…) | Não |
| Similarity search / top-k por query | Não |
| Índice persistente entre execuções | **Sim** — `state/repo_index.json` (código dos repos, ver seção 13) |
| Reranker cross-encoder | Não |
| Ponderação por IDF | **Sim** — no de/para de serviços (`src/marcar.py`) |

**Por quê assim?** O corpus por execução é **pequeno e conhecido** (Figma + regras + poucos docs da pasta `inputs/`). Para esse caso, retrieve estrutural + filtro lexical é mais barato, determinístico e suficiente para controlar tokens. RAG vetorial passa a valer quando houver **base grande** (wiki, Confluence, dezenas de specs) e queries variáveis.

#### Analogia rápida

- **RAG desta pipeline:** “pegue estes arquivos desta pasta, fatie, filtre o que parece regra/API, comprima, entregue ao modelo.”
- **RAG vetorial:** “indexe milhares de docs; para esta pergunta, busque os k trechos mais similares semanticamente.”

Evolução natural (próximo passo): manter `doc_compress` / budget e trocar só o **Retrieve** por embeddings + top-k, sem mudar o resto do pipeline.

### 6. `context_build` (`src/context_builder.py`)

**Papel:** montar o prompt em duas partes (favorável a **prompt caching**):

1. **`system`** — texto fixo de `prompts/system.compact.txt` (prefixo estável).
2. **`dynamic`** — JSON enxuto:
   - `comando` (`Gerar openapi|mermaid|historia|prd`)
   - `state` (metadados, sem docs brutos)
   - `contexto_comprimido` (saída do RAG)
   - `template` (esqueleto; se estourar budget, trunca o template)

Estimativa de tokens: `len(texto) // 4` (heurística, não tokenizer oficial).

### 7. `reason` (`src/reason.py`)

**Papel:** preparar a geração, sem prosa na saída.

- **`build_llm_package`**: gera JSON dual:
  - `openai`: `instructions` + `input` + `store: true` (encadeamento futuro via `previous_response_id`)
  - `claude`: `system` com `cache_control: ephemeral` + `messages`
- **`dry_run_scaffold`**: preenche o template localmente (sem API) para `openapi`, `mermaid`, `historia` e **`prd`**.
- Na história/PRD, o scaffold usa UI + regras + **`engenharia`** + `consolidated` (RF/AC + stack/NFR + handoff SDD).
- **`--live`**: slot ainda não implementado — deve consumir o pacote já comprimido.

### 8. `emit` (`src/emit.py` + `also_emit` em `run.py`)

**Papel:** gravar o arquivo do tipo pedido em `outputs/` (+ `llm_package_*.json`).

- Um tipo → um arquivo principal (`openapi.yaml`, `sequence.mmd`, `historia.md`, `PRD.md`).
- Exceção: `historia` declara `also_emit: [prd]` em `config/pipeline.yaml` — `run.py` gera **história e PRD** na mesma execução (mesmo contexto comprimido, dois templates).

### Diagrama de dados (o que viaja vs o que para)

```
figma.json ──────► preprocess ──► ui {inputs, actions, columns} ──┐
regras.yaml ─────► preprocess ──► regras {bloqueios, …} ──────────┤
engenharia.yaml ► preprocess ──► engenharia {stack, NFR v1} ─────┼─► rag_compress ─► consolidated
docs *.txt ──────► doc_compress ─► resumos/consolidado docs ─────┘         │
                                                                            ▼
state/workflow.json ◄── só metadados                               context_builder
                                                                            │
                                                                            ▼
                                                                   llm_package_*.json
                                                                   + artefato(s) em outputs/
                                                                   (historia → também PRD.md)
```

---

## Artefatos gerados

| Comando | Template | Saída |
|---------|----------|--------|
| `openapi` | `templates/openapi.skeleton.yaml` | `outputs/openapi.yaml` (+ `canonical-spec.yaml` na run) |
| `mermaid` | `templates/mermaid.skeleton.md` | `outputs/sequence.mmd` |
| `historia` | `templates/historia.skeleton.md` | `outputs/historia.md` **+** `outputs/PRD.md` |
| `prd` | `templates/prd.skeleton.md` | `outputs/PRD.md` |

Toda run também grava **`canonical-spec.yaml`** e validações em `runs/<run_id>/` (espelhadas conforme o layout da execução). `historia` emite também o **PRD** (`also_emit` em `config/pipeline.yaml`): a história é o recorte de implementação (**BDD funcional + DoD NFR**); o PRD é o documento canônico para um **SDD** futuro (arquitetura, contrato, tasks, NFR-R/O/S/D).

Além do artefato, a pipeline grava o **pacote LLM** (contexto já comprimido):

- `outputs/llm_package_openapi.json`
- `outputs/llm_package_mermaid.json`
- `outputs/llm_package_historia.json`
- `outputs/llm_package_prd.json`

Cada pacote inclui variantes `openai` e `claude` para plugar a API no modo `--live`.

### PRD → SDD

O `PRD.md` nasce com:

- **frontmatter YAML** (`id`, `artifacts`, `sdd.expected`, `nfr_ids`) para parsers de SDD
- RF (`RF-xx`) a partir das regras/UI
- AC (`AC-xx`) BDD alinhados à história
- NFR (`NFR-R|O|S|D-xx`) a partir de `engenharia.yaml` (baseline v1)
- contrato de dados (entrada/saída/ações)
- seção **Handoff para SDD** (o que o próximo estágio deve gerar)
- contexto comprimido do Prompt-less (sem texto bruto)

Fluxo sugerido:

```
Figma + regras + docs
        → Prompt-less (historia + PRD + opcionalmente openapi/mermaid)
                → SDD consome PRD.md
                        → architecture / api / tasks
```

### Regras de tradução (quando o LLM/live estiver ativo)

**OpenAPI**

- `inputs` do Figma → propriedades de `requestBody` (tipos inferidos: idade→integer, etc.)
- listas/tabelas → schema da resposta `200`
- bloqueios em regras → respostas `400/401/403/404/422` referenciando `components.schemas.Error`

**Mermaid**

- Atores fixos: Frontend (Tela), BFF, API de Domínio
- Condições de regra → blocos `alt` / `opt`
- Verbos/paths alinhados às actions da UI / OpenAPI

**História**

- Título, Contexto (1 linha), Critérios BDD (Dado/Quando/Então), Dependências
- Critérios = tradução das condições de `regras.yaml`
- Payloads alinhados ao Figma
- Escopo técnico + DoD NFR a partir de `engenharia.yaml` (baseline v1: timeout/retry + logs + documentação)

**PRD**

- Preencher `prd.skeleton.md` sem remover o frontmatter
- RF/AC rastreáveis; dados da UI; regras → erros HTTP
- NFR-R / NFR-O / NFR-S / NFR-D a partir do baseline de engenharia
- Handoff SDD lista artefatos esperados + rastreio RF/AC/NFR

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

`--live` está reservado para plugar clientes OpenAI/Claude em `src/reason.py` usando o JSON já montado em `outputs/llm_package_*.json`. Hoje levanta `NotImplementedError` de propósito.

### Testes e CI

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -v --tb=short
```

Workflow GitHub Actions (`.github/workflows/ci.yml`): `compileall` + validação de `permission_profiles.yaml` + pytest + smoke `plan_repos --help`.

## Exemplos de uso

Os exemplos abaixo assumem que você está em `pipeline/` com o venv ativo (ou use o prefixo `.venv/bin/python`).

### 1. Quickstart com os insumos de exemplo

O repositório já traz `inputs/figma.json`, `inputs/regras.yaml`, `inputs/engenharia.yaml` e docs de amostra.

```bash
# História técnica (BDD + NFR) + PRD (insumo para SDD)
.venv/bin/python -m src.run historia --dry-run

# Ver saídas (seção NFR na história e no PRD)
ls outputs/historia.md outputs/PRD.md
sed -n '/## Não-funcionais/,/## Dependências/p' outputs/historia.md
```

Saída esperada no terminal (resumo):

```json
{
  "outputs": {
    "historia": ".../outputs/historia.md",
    "prd": ".../outputs/PRD.md"
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
| `outputs/openapi.yaml` | Contrato (ainda com markers no dry-run) |
| `outputs/sequence.mmd` | Sequência Frontend → BFF → API |
| `outputs/historia.md` | História BFF/MFE (BDD) |
| `outputs/PRD.md` | PRD canônico para SDD |

### 3. Só o PRD (sem reemitir a história)

Útil quando a história já existe e você quer regenerar o handoff SDD:

```bash
.venv/bin/python -m src.run prd --dry-run
cat outputs/PRD.md
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

# 3) Encaminhe o PRD ao estágio SDD
cp outputs/PRD.md ../sdd/inbox/PRD.md
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

# C) O SDD consome o frontmatter de outputs/PRD.md
#    campos: artifacts.* e sdd.expected
#    → architecture.md, sequence_refined.mmd, api_contract.yaml, tasks.md
grep -A20 '^---' outputs/PRD.md | head -25
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

### 10. Prompt-less → Devin CLI (implementação)

A pipeline **gera** o contexto curto; o [Devin CLI](https://docs.devin.ai/) **implementa** no repo de código. Não aponte o Devin para `inputs/` brutos (ex.: txt de 3000 linhas) — só para `outputs/` / `docs/prompt-less/`.

```
inputs/ (Figma, regras, engenharia, docs)
        │
        ▼
   Prompt-less (compressão + artefatos)
        │
        ▼
 outputs/PRD.md + historia.md (+ openapi/mermaid)
        │
        ▼
  docs/prompt-less/ no repo do app
        │
        ▼
   Devin CLI → código + PR
        │
        ▼  (opcional)
   /handoff → Devin Cloud
```

**Script incluso**

```bash
chmod +x scripts/devin-from-promptless.sh

# Gera historia+PRD, copia para o app e abre o Devin
./scripts/devin-from-promptless.sh /caminho/do/seu-bff

# Também gera OpenAPI + Mermaid
./scripts/devin-from-promptless.sh /caminho/do/seu-bff --full

# Só prepara docs/prompt-less/ (sem chamar `devin`)
./scripts/devin-from-promptless.sh /caminho/do/seu-bff --dry-prep

# Pasta com TODOS os repos: escaneia → mapa → marcadores → um pacote por repo
./scripts/devin-from-promptless.sh --workspace ~/dev/repos --dry-prep
```

O script grava em `APP/docs/prompt-less/`:

| Arquivo | Papel |
|---------|--------|
| `PRD.md` / `historia.md` | Fonte da verdade (RF/AC/NFR) |
| `openapi.yaml` / `sequence.mmd` | Contrato e fluxo (se `--full` ou já existirem) |
| `engenharia.yaml` | Stack + baseline NFR v1 |
| `DEVIN_PROMPT.md` | Prompt enxuto passado ao `devin -- …` |

**Manual (sem script)**

```bash
.venv/bin/python -m src.run historia --dry-run
mkdir -p ../meu-app/docs/prompt-less
cp outputs/PRD.md outputs/historia.md ../meu-app/docs/prompt-less/
cd ../meu-app
devin -- "Implemente docs/prompt-less/PRD.md e historia.md. Respeite NFR-R/O/S/D (README, CHANGELOG, docs de API). Não releia specs brutas."
```

Instalação do CLI (se ainda não tiver): `curl -fsSL https://cli.devin.ai/install.sh | bash`  
Handoff cloud, se a tarefa crescer: `/handoff` na sessão Devin ([docs](https://cognitionai.mintlify.app/work-with-devin/devin-cli)).

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

`historia.md` e `PRD.md` passam a ter uma seção de **estado atual** e uma de **gaps**, ambas derivadas do índice:

```markdown
**Endpoints existentes** (2):
- `cadastro-cliente-api: POST /v1/clientes/cadastro`
- `cadastro-cliente-api: GET /v1/clientes/{cpf}`

**Códigos HTTP já tratados:** `201`, `400`, `409`

### Gaps entre regra e código
- `400` — **já tratado no código**; validar gatilho: CPF inválido
- `401` — **não encontrado no código**; implementar: sem autenticação
- códigos no código sem regra correspondente no doc: `409` _(regra implícita ou legado — confirmar)_
```

O efeito prático é a história deixar de descrever tudo como novo: o que já existe vira ajuste, o que falta vira implementação, e código sem regra no documento aparece como pergunta para o negócio. O índice **não** entra no prompt — ele alimenta o scaffold e fica em `state/`, fora do budget de tokens.

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
| `runs/<id>/manifest.json` | status versionado, objective, timestamps, `status_history` |
| `runs/<id>/events.jsonl` | trilha append-only de eventos |
| `runs/<id>/artifacts/` | artefatos da run (incl. `canonical-spec.yaml`) |
| `runs/<id>/artifacts/contextos/<svc>/` | pacotes por serviço (`--all-contexts`) |
| `runs/<id>/validations/` | `provenance.json`, `spec-validation.json` |
| `runs/<id>/validations/contextos/<svc>/` | `spec-validation.json` por serviço |
| `runs/<id>/state.json` | estado da execução (sem texto bruto) |

**Contrato de contexto (único):** tudo que é por serviço vive em `contextos/<id>/` — na run (`artifacts/`, `validations/`) e no espelho (`outputs/contextos/<id>/`). O id do serviço é validado com a mesma regra do `run_id`.

### Storage seguro da run

`runs/` é o diretório autorizado da execução, e a pipeline trata isso como fronteira de segurança:

| Garantia | Como |
|----------|------|
| `run_id` canônico | `[A-Za-z0-9_][A-Za-z0-9_-]*` até 64 chars; `..`, `/`, `\`, espaço, ponto e `latest` são `InvalidRunId` |
| Sem escape de diretório | `run_dir.resolve()` precisa ficar sob `<root>/runs` (pega até symlink plantado) → `UnsafeRunPath` |
| Sem JSON parcial | manifest, `state.json`, `provenance.json`, `latest.json`, `canonical-spec.yaml` e pacotes LLM usam write-temp + `os.replace` (`src/runtime/atomic_io.py`) |
| Colisão de id | `bootstrap()` cria o diretório com `mkdir` exclusivo; id repetido = `RunIdCollision` (retomada explícita: `bootstrap(resume=True)`) |
| Transição de status | `set_status` valida a transição e usa `version` monotônica; escrita com versão obsoleta = `RunStateConflict`; estado terminal não reabre |
| Espelho publicado por manifesto | `outputs/.mirror-manifest.json` (run_id + sha256 por arquivo) é o ponto de commit; obsoletos da publicação anterior são removidos depois, symlinks são ignorados e arquivos nunca publicados nunca são apagados |

O espelho em `outputs/` é **last-writer-wins** por design (compatibilidade com os scripts Devin); a fonte da verdade auditável continua sendo `runs/<id>/`.

### Provenance e claims

Na compressão RAG, trechos viram **claims** com `SourceRef` (arquivo/linha/origem). Claims sem fonte válida falham o gate (`CLAIM_WITHOUT_SOURCE` / `CLAIM_SOURCE_INVALID`). Descarte é reportado em `validations/provenance.json`. Runs bloqueadas pelo quality gate **preservam** `claims` e `discarded` no payload JSON.

### Canonical Spec + quality gate

Antes de renderizar história/PRD, a pipeline monta o IR (`src/spec/builder.py`) e valida (`src/validators/`):

- ambiguidade de status HTTP → `PipelineBlocked` (não default silencioso para 422)
- defaults/inferências explícitos (`origin`, `confidence`, `requires_review`)
- `unexpected_inferences` conta ResolvedValues `default|inferred` sem review
- traceability de claim IDs (órfãos = warning)

Artefato: `canonical-spec.yaml` ao lado dos demais outputs da run.

### Ciclo executor (`close_loop`)

Fecha o loop **spec × ExecutionResult × policy de camada**:

```bash
.venv/bin/python -m src.close_loop \
  --spec runs/<id>/artifacts/canonical-spec.yaml \
  --result tests/fixtures/executor/execution_ok.json \
  --out /tmp/verify

# marcar aprovação / tentativa de reparo
.venv/bin/python -m src.close_loop --spec ... --result ... --approve
.venv/bin/python -m src.close_loop --spec ... --result ... --attempt 1 --layer bff
```

Policy (`config/permission_profiles.yaml` + `src/executors/policy.py`):

- writes/comandos allow/deny por camada (`bff`, `api`, `mfe`, …)
- comandos parseados como argv (`shlex`); `&&` / `;` / `||` negam
- paths normalizados (`normalize_repo_path`) — rejeita absoluto e `..`
- verify fail-closed para layer desconhecido; `NO_TESTS_REPORTED` é error em code change
- `FILE_OUT_OF_SCOPE` → `required_reverts` (não amplia `editable_surface`)

O adapter Devin (`src/executors/devin.py`) é stub até o ticket E2E da série 2.

### Plano multi-repo (`plan_repos`)

```bash
.venv/bin/python -m src.plan_repos
.venv/bin/python -m src.plan_repos --service gestao-de-ofertas --out runs/plan/
# → implementation_plan.yaml + .json (ondas, contratos, origin: heuristic, requires_review)
```

### Autoaperfeiçoamento (`improve`)

```bash
.venv/bin/python -m src.improve --verify-report /tmp/verify/verify-report.json
.venv/bin/python -m src.improve --out state/knowledge   # demo sem report (falha AMBIGUOUS_HTTP)
```

Fluxo: diagnose (padrões em `failure-patterns.yaml`) → propostas limitadas (`playbook.yaml`) → eval suite → decisão. Status positivo = **`approved_for_experiment`** — não aplica mudança de código (apply + rollback = série 2).

### Evals e testes

```bash
.venv/bin/pytest -v --tb=short
# esperado: 83 passed
```

Fixtures em `tests/fixtures/` (happy_path, access_denied, ambiguous_status, two_services). Scoring por camada: `ingestion` / `canonical_spec` / `artifacts` / `provenance`. CI em `.github/workflows/ci.yml` (compileall + YAML de profiles + pytest + smoke `plan_repos`).

---

## Estrutura do repositório

```
pipeline/
├── README.md
├── CHANGELOG.md
├── requirements.txt
├── pytest.ini
├── .github/workflows/ci.yml
├── scripts/
│   ├── scan-repos.sh              # pasta de repos → mapa-servicos.yaml (de/para)
│   └── devin-from-promptless.sh   # scan + index + marcar + artefatos → Devin CLI
├── config/
│   ├── pipeline.yaml              # budget, stages, caching, mapeamento de artefatos
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
    ├── run.py                     # pipeline + Canonical Spec + runtime
    ├── close_loop.py              # verify / approve / repair
    ├── plan_repos.py              # implementation_plan multi-repo
    ├── improve.py                 # diagnose → propose → eval → gate
    ├── ingest.py / docs_ingest.py / preprocess.py / engenharia.py
    ├── servicos.py / marcar.py / repo_index.py
    ├── state_store.py / doc_compress.py / rag_compress.py
    ├── context_builder.py / reason.py / emit.py / economia.py
    ├── domain/                    # Claim, SourceRef, DocumentChunk, CanonicalSpec
    ├── runtime/                   # RunContext, RunStore, EventStore, atomic_io
    ├── spec/                      # builder do IR
    ├── validators/                # quality gate
    ├── renderers/                 # história/PRD a partir do IR
    ├── executors/                 # policy, verify, loop, Devin adapter
    ├── planning/                  # grafo, camadas, plan
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

Artefatos e encadeamento:

```yaml
artifacts:
  historia:
    template: templates/historia.skeleton.md
    output: outputs/historia.md
    also_emit: [prd]          # mesma run → também outputs/PRD.md
  prd:
    template: templates/prd.skeleton.md
    output: outputs/PRD.md
```

Ajuste o budget conforme o provedor (janela, preço de cache) e o risco de “cortar demais” sinais.

---

## Dependências

- Python 3.9+ (CI usa 3.11)
- `PyYAML`
- `python-docx` (`.docx`)
- `pytest` (suíte de integração / evals)
- macOS: `textutil` nativo para `.doc` legado  
  Linux: `antiword` (opcional) para `.doc`

---

## Métricas e observabilidade

Cada execução imprime JSON com:

- `output` / `outputs` — caminho principal e mapa de todos os arquivos emitidos (ex.: `historia` + `prd`)
- `llm_package` / `llm_packages` — pacotes por tipo
- `est_tokens` — estimativa do pacote principal (chars/4)
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

Preços são tabelas de referência (USD / 1M tokens). Atualize `MODELOS` em `src/economia.py` se o vendor mudar a lista. Estimativa de tokens continua sendo `chars÷4` (não tokenizer oficial).

---

## Limitações atuais e próximos passos

**Limitações**

- Modo `--live` (chamada real OpenAI/Claude) ainda não implementado
- Adapter Devin no `close_loop` é stub (E2E real = série 2)
- `improve` não aplica propostas nem faz rollback — só `approved_for_experiment`
- IR ainda não regenera OpenAPI/Mermaid a partir do Canonical Spec
- Resumo de docs é **extrativo por regex**, não LLM small (bom custo; pode perder nuance)
- Estimativa de tokens é heurística (`len/4`), não tokenizer oficial
- State backend `redis` está previsto no YAML, implementação atual é **arquivo** / `runs/`

**Próximos passos (série 2 — ver CHANGELOG [Unreleased])**

1. IR → OpenAPI / Mermaid a partir do Canonical Spec
2. Plugar OpenAI Responses / Claude Messages no `reason.py` (`--live`)
3. Devin CLI real no `close_loop`
4. Orquestração declarativa via stages em `pipeline.yaml`
5. Tokenizer oficial + Redis opcional
6. Execução concorrente por ondas + apply/rollback de propostas
7. Hardening profundo (debugger, injection, recovery, golden recall)
8. Consumidor SDD que leia `outputs/PRD.md` e gere architecture/tasks com RF + NFR
9. Evoluir `engenharia.yaml` v2+ (circuit breaker, metrics, tracing) sem inchir o prompt

---

## Lição de design

> Sistemas LLM em produção funcionam melhor quando o modelo vê a **informação certa**, não a **maior quantidade** de informação.

O **Prompt-less** aplica isso ao domínio de artefatos de tech lead: Figma, regras, engenharia e documentos longos viram um contexto pequeno, estável e auditável — pronto para gerar OpenAPI, Mermaid, histórias (**funcional + NFR**) e **PRD para SDD** com custo previsível, com harness (runtime, provenance, Canonical Spec, verify) entre o sinal comprimido e a implementação.
