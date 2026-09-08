# Prompt-less

> Gera OpenAPI, fluxo Mermaid e história técnica a partir de Figma, regras e docs — com contexto comprimido e custo de tokens sob controle.

**Repositório:** [github.com/ilaraca/prompt-less](https://github.com/ilaraca/prompt-less)

Pipeline de tech lead que transforma insumos desidratados (UI, regras, TXT/DOCX) em três artefatos: contrato de API, diagrama de sequência e história BFF/MFE. Em vez de mandar tudo ao LLM, filtra o sinal, comprime o contexto e só então gera.

Inspirada nas práticas descritas por Yuval Ben-itzhak (*How I reduced LLM token costs by ~90%*): o custo real não está no prompt “bonito”, e sim na **explosão de contexto** (system repetido, tools verbosas, histórico, RAG bruto, logs).

---

## Objetivo

Receber insumos de produto/UX/negócio e emitir **somente o artefato final**, com:

- contexto **comprimido e estruturado** antes do modelo de raciocínio;
- estado do workflow **fora do prompt**;
- prefixo de system/tools **estável e cacheável** (OpenAI / Claude);
- budget explícito de tokens (alvo ~650; teto ~2000).

**Princípio:** nunca enviar dados brutos ao modelo se puderem ser filtrados ou comprimidos antes.

---

## Aplicabilidade

### Onde esta pipeline faz sentido

| Cenário | Por quê |
|--------|---------|
| **Geração assistida de contratos OpenAPI** a partir de Figma + regras | Inputs/listas viram schemas; bloqueios viram 4xx tipados |
| **Diagramas de sequência Frontend → BFF → API** | Traduz regras em `alt`/`opt` sem reenviar specs inteiras |
| **Histórias técnicas BFF/MFE** (BDD) | Critérios espelham `regras.yaml`; payloads espelham UI |
| **Onboarding / tech lead docs** | Padroniza artefatos a partir de fontes heterogêneas |
| **Specs longas (milhares de linhas)** | Compressão hierárquica: sinal de negócio entra; ruído sai |
| **Agentes multi-etapa com custo controlado** | State externo + pacote LLM enxuto por request |
| **Pré-processamento barato + raciocínio caro** | Camada local (“modelo pequeno”) + slot para LLM grande |

### Onde *não* é a melhor ferramenta (ainda)

| Cenário | Motivo |
|--------|--------|
| Geração 100% automática em produção sem revisão humana | Dry-run preenche esqueleto; `--live` (API) ainda é slot a plugar |
| Documentos sem sinais lexicais de negócio | Resumo extrativo prioriza termos (regra, HTTP, endpoint…); texto só narrativo pode ser filtrado demais |
| Extração fiel linha a linha de PDFs jurídicos/contratos | Foco é **sinal para artefato técnico**, não arquivo íntegro |
| `.doc` legado fora do macOS sem `antiword` | Conversão depende de `textutil` (macOS) ou `antiword` |

### Público-alvo

- Tech Leads / Arquitetos montando pipeline de artefatos
- Times de plataforma de IA que precisam **orçar tokens**
- Squads BFF/MFE que partem de Figma + regras desidratadas

---

## Arquitetura

```
Dados brutos (figma.json, regras.yaml, *.txt/*.docx/*.doc/*.md)
        │
        ▼
   [ingest] ─────────────── carrega só o necessário
        │
        ▼
 [preprocess] ───────────── desidrata UI/regras; docs com metadados+texto
        │
        ▼
 [state_write] ──────────── arquivo: estado SEM texto bruto
        │
        ├──────────────────► docs: chunk → resumo (sinais) → consolidado
        │
 [rag_compress] ─────────── UI/regras + docs → consolidated ≤ budget
        │
        ▼
 [context_build] ────────── system estável (cache) + dynamic enxuto
        │
        ▼
   [reason] ─────────────── pacote OpenAI/Claude  |  dry-run scaffold
        │
        ▼
    [emit] ──────────────── outputs/openapi.yaml | sequence.mmd | historia.md
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
| Template do tipo pedido | `ingest.py` | esqueleto OpenAPI / Mermaid / História |
| `*.txt`, `*.md`, `*.docx`, `*.doc` | `docs_ingest.py` | texto extraído + metadados (`name`, `lines`, `chars`, `est_tokens_raw`) |

- `.docx` → `python-docx` (parágrafos + tabelas).
- `.doc` → `textutil` (macOS) ou `antiword`.
- `README.txt` em `inputs/` é ignorado de propósito.

**Saída desta etapa:** um dict `raw` com `tipo`, `figma`, `regras`, `template`, `documents[]`.

### 2. `preprocess` (`src/preprocess.py`)

**Papel:** camada “modelo pequeno” **local** (sem LLM) — tira metadados visuais e prosa.

- **Figma** → só `inputs` (nome/tipo/required), `actions` (id/method/path), `columns` (nome/tipo). Tipos são inferidos (`idade`→integer, etc.).
- **Regras** → `fluxo`, `happy`, `bloqueios` (trigger + status HTTP), `decisoes`.
- **Docs** → mantém texto **só nesta etapa intermediária** para a compressão; o state depois descarta o corpo.

**Saída:** `slim` = UI + regras desidratadas + documents + template.

### 3. `state_write` (`src/state_store.py`)

**Papel:** substituir histórico de conversa por **estado externo** (padrão do artigo).

Grava em `state/workflow.json` apenas:

- `tipo`, `fluxo`, nomes de `inputs`, `actions`, `bloqueios`
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

`SIGNAL_RE` detecta termos de negócio/API, por exemplo: `regra`, `bloqueio`, `http`, `endpoint`, `path`, `request`, `response`, `dado`, `quando`, `então`, `auth`, `permiss`, `api`, `bff`, `status`, `openapi`…

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
| Índice persistente entre execuções | Não |
| Reranker cross-encoder | Não |

**Por quê assim?** O corpus por execução é **pequeno e conhecido** (Figma + regras + poucos docs da pasta `inputs/`). Para esse caso, retrieve estrutural + filtro lexical é mais barato, determinístico e suficiente para controlar tokens. RAG vetorial passa a valer quando houver **base grande** (wiki, Confluence, dezenas de specs) e queries variáveis.

#### Analogia rápida

- **RAG desta pipeline:** “pegue estes arquivos desta pasta, fatie, filtre o que parece regra/API, comprima, entregue ao modelo.”
- **RAG vetorial:** “indexe milhares de docs; para esta pergunta, busque os k trechos mais similares semanticamente.”

Evolução natural (próximo passo): manter `doc_compress` / budget e trocar só o **Retrieve** por embeddings + top-k, sem mudar o resto do pipeline.

### 6. `context_build` (`src/context_builder.py`)

**Papel:** montar o prompt em duas partes (favorável a **prompt caching**):

1. **`system`** — texto fixo de `prompts/system.compact.txt` (prefixo estável).
2. **`dynamic`** — JSON enxuto:
   - `comando` (`Gerar openapi|mermaid|historia`)
   - `state` (metadados, sem docs brutos)
   - `contexto_comprimido` (saída do RAG)
   - `template` (esqueleto; se estourar budget, trunca o template)

Estimativa de tokens: `len(texto) // 4` (heurística, não tokenizer oficial).

### 7. `reason` (`src/reason.py`)

**Papel:** preparar a geração, sem prosa na saída.

- **`build_llm_package`**: gera JSON dual:
  - `openai`: `instructions` + `input` + `store: true` (encadeamento futuro via `previous_response_id`)
  - `claude`: `system` com `cache_control: ephemeral` + `messages`
- **`dry_run_scaffold`**: preenche o template localmente (sem API) para validar a pipeline.
- **`--live`**: slot ainda não implementado — deve consumir o pacote já comprimido.

### 8. `emit` (`src/emit.py`)

**Papel:** gravar um único arquivo por tipo em `outputs/`, mais o `llm_package_*.json` (gravado em `run.py`).

### Diagrama de dados (o que viaja vs o que para)

```
figma.json ──► preprocess ──► ui {inputs, actions, columns} ──┐
regras.yaml ► preprocess ──► regras {bloqueios, …} ──────────┼─► rag_compress ─► consolidated
docs *.txt ─► doc_compress ─► resumos/consolidado docs ──────┘         │
                                                                       ▼
state/workflow.json ◄── só metadados                          context_builder
                                                                       │
                                                                       ▼
                                                              llm_package_*.json
                                                              + artefato em outputs/
```

---

## Artefatos gerados

| Comando | Template | Saída |
|---------|----------|--------|
| `openapi` | `templates/openapi.skeleton.yaml` | `outputs/openapi.yaml` |
| `mermaid` | `templates/mermaid.skeleton.md` | `outputs/sequence.mmd` |
| `historia` | `templates/historia.skeleton.md` | `outputs/historia.md` |

Além do artefato, a pipeline grava o **pacote LLM** (contexto já comprimido):

- `outputs/llm_package_openapi.json`
- `outputs/llm_package_mermaid.json`
- `outputs/llm_package_historia.json`

Cada pacote inclui variantes `openai` e `claude` para plugar a API no modo `--live`.

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

---

## Insumos suportados

Coloque os arquivos em `pipeline/inputs/`:

| Arquivo / padrão | Obrigatório? | Uso |
|------------------|--------------|-----|
| `figma.json` | Não | Inputs, botões/actions, colunas de lista |
| `regras.yaml` | Não | Happy path, bloqueios, tabela de decisão |
| `*.txt`, `*.md` | Não | Specs/notas longas (comprimidas) |
| `*.docx` | Não | Word moderno (`python-docx`) |
| `*.doc` | Não | Word legado (`textutil` no macOS ou `antiword`) |

`README.txt` em `inputs/` é **ignorado** na ingestão de documentos.

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
.venv/bin/python -m src.run historia --dry-run
```

### Live (API)

`--live` está reservado para plugar clientes OpenAI/Claude em `src/reason.py` usando o JSON já montado em `outputs/llm_package_*.json`. Hoje levanta `NotImplementedError` de propósito.

---

## Estrutura do repositório

```
pipeline/
├── README.md
├── requirements.txt
├── config/
│   ├── pipeline.yaml         # budget, stages, caching, mapeamento de artefatos
│   └── tools.compact.yaml    # definições de tools sem prosa (economia de tokens)
├── prompts/
│   └── system.compact.txt    # system estável → candidato a prompt cache
├── templates/                # esqueletos preenchidos no reason/emit
├── inputs/                   # corpus da execução (Figma, regras, docs)
├── state/                    # estado externo (sem histórico/docs brutos)
├── outputs/                  # artefato final + llm_package_*.json
└── src/
    ├── run.py                # orquestra as 8 etapas e imprime métricas
    ├── ingest.py             # carrega figma/regras/template
    ├── docs_ingest.py        # extrai texto de txt/md/docx/doc
    ├── preprocess.py         # desidrata UI/regras (pré-LLM)
    ├── state_store.py        # persiste estado mínimo em JSON
    ├── doc_compress.py       # compressão hierárquica + SIGNAL_RE
    ├── rag_compress.py       # retrieve estrutural + merge UI/regras/docs
    ├── context_builder.py    # system + dynamic ≤ budget
    ├── reason.py             # pacote OpenAI/Claude + dry-run
    └── emit.py               # escreve arquivo único em outputs/
```

Leitura recomendada do código, nesta ordem: `run.py` → `rag_compress.py` → `doc_compress.py` → `context_builder.py`.

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

Ajuste esses valores conforme o provedor (janela, preço de cache) e o risco de “cortar demais” sinais.

---

## Dependências

- Python 3.9+
- `PyYAML`
- `python-docx` (`.docx`)
- macOS: `textutil` nativo para `.doc` legado  
  Linux: `antiword` (opcional) para `.doc`

---

## Métricas e observabilidade

Cada execução imprime JSON com:

- `est_tokens` — estimativa do pacote (chars/4)
- `rag.raw` / `rag.compressed` — antes/depois da compressão
- `rag.doc_reduction_pct` — % de redução documental
- `docs_ingested` — lista de arquivos e linhas

Use essas métricas para validar que a pipeline continua “barata” ao crescer o volume de insumos.

---

## Limitações atuais e próximos passos

**Limitações**

- Modo `--live` (chamada real OpenAI/Claude) ainda não implementado
- Resumo de docs é **extrativo por regex**, não LLM small (bom custo; pode perder nuance)
- Estimativa de tokens é heurística (`len/4`), não tokenizer oficial
- State backend `redis` está previsto no YAML, implementação atual é **arquivo**

**Próximos passos sugeridos**

1. Plugar OpenAI Responses / Claude Messages no `reason.py` usando `llm_package_*.json`
2. Trocar extrativo por modelo small só quando o score de sinais for baixo
3. Persistência Redis + TTL alinhado ao cache Claude (5m / 1h)
4. Telemetria de custo real (tokens billable + cache hits)

---

## Lição de design

> Sistemas LLM em produção funcionam melhor quando o modelo vê a **informação certa**, não a **maior quantidade** de informação.

Esta pipeline aplica isso ao domínio de **artefatos de tech lead**: Figma, regras e documentos longos viram um contexto pequeno, estável e auditável — pronto para gerar OpenAPI, Mermaid e histórias com custo previsível.
