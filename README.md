# Prompt-less

> Gera OpenAPI, fluxo Mermaid, história técnica e PRD a partir de Figma, regras e docs — com contexto comprimido e custo de tokens sob controle.

**Repositório:** [github.com/ilaraca/prompt-less](https://github.com/ilaraca/prompt-less)

Pipeline de tech lead que transforma insumos desidratados (UI, regras, TXT/DOCX) em artefatos: contrato de API, diagrama de sequência, história BFF/MFE e **PRD.md** (insumo para SDD). Em vez de mandar tudo ao LLM, filtra o sinal, comprime o contexto e só então gera.

Inspirada nas práticas descritas por Yuval Ben-itzhak (*How I reduced LLM token costs by ~90%*): o custo real não está no prompt “bonito”, e sim na **explosão de contexto** (system repetido, tools verbosas, histórico, RAG bruto, logs).

---

## Objetivo

Receber insumos de produto/UX/negócio e emitir **artefato(s) finais sem prosa**, com:

- contexto **comprimido e estruturado** antes do modelo de raciocínio;
- estado do workflow **fora do prompt**;
- prefixo de system/tools **estável e cacheável** (OpenAI / Claude);
- budget explícito de tokens (alvo ~650; teto ~2000);
- **PRD.md** gerado junto com a história, como insumo canônico para **SDD**.

**Princípio:** nunca enviar dados brutos ao modelo se puderem ser filtrados ou comprimidos antes.

---

## Aplicabilidade

### Onde esta pipeline faz sentido

| Cenário | Por quê |
|--------|---------|
| **Geração assistida de contratos OpenAPI** a partir de Figma + regras | Inputs/listas viram schemas; bloqueios viram 4xx tipados |
| **Diagramas de sequência Frontend → BFF → API** | Traduz regras em `alt`/`opt` sem reenviar specs inteiras |
| **Histórias técnicas BFF/MFE** (BDD) | Critérios espelham `regras.yaml`; payloads espelham UI |
| **PRD.md para SDD (Spec-Driven Development)** | `historia` emite também o PRD com RF/AC, contrato de dados e handoff |
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

- Tech Leads / Arquitetos montando pipeline de artefatos e PRD→SDD
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
    [emit] ──────────────── outputs/openapi.yaml | sequence.mmd | historia.md | PRD.md
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
| Template do tipo pedido | `ingest.py` | esqueleto OpenAPI / Mermaid / História / PRD |
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
- No PRD, o scaffold usa UI + regras + `consolidated` do RAG (RF/AC, dados, handoff SDD).
- **`--live`**: slot ainda não implementado — deve consumir o pacote já comprimido.

### 8. `emit` (`src/emit.py` + `also_emit` em `run.py`)

**Papel:** gravar o arquivo do tipo pedido em `outputs/` (+ `llm_package_*.json`).

- Um tipo → um arquivo principal (`openapi.yaml`, `sequence.mmd`, `historia.md`, `PRD.md`).
- Exceção: `historia` declara `also_emit: [prd]` em `config/pipeline.yaml` — `run.py` gera **história e PRD** na mesma execução (mesmo contexto comprimido, dois templates).

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
                                                              + artefato(s) em outputs/
                                                              (historia → também PRD.md)
```

---

## Artefatos gerados

| Comando | Template | Saída |
|---------|----------|--------|
| `openapi` | `templates/openapi.skeleton.yaml` | `outputs/openapi.yaml` |
| `mermaid` | `templates/mermaid.skeleton.md` | `outputs/sequence.mmd` |
| `historia` | `templates/historia.skeleton.md` | `outputs/historia.md` **+** `outputs/PRD.md` |
| `prd` | `templates/prd.skeleton.md` | `outputs/PRD.md` |

`historia` emite também o **PRD** (`also_emit` em `config/pipeline.yaml`): a história é o recorte de implementação; o PRD é o documento canônico para um **SDD** futuro (arquitetura, contrato, tasks).

Além do artefato, a pipeline grava o **pacote LLM** (contexto já comprimido):

- `outputs/llm_package_openapi.json`
- `outputs/llm_package_mermaid.json`
- `outputs/llm_package_historia.json`
- `outputs/llm_package_prd.json`

Cada pacote inclui variantes `openai` e `claude` para plugar a API no modo `--live`.

### PRD → SDD

O `PRD.md` nasce com:

- **frontmatter YAML** (`id`, `artifacts`, `sdd.expected`) para parsers de SDD
- RF (`RF-xx`) a partir das regras/UI
- AC (`AC-xx`) BDD alinhados à história
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

**PRD**

- Preencher `prd.skeleton.md` sem remover o frontmatter
- RF/AC rastreáveis; dados da UI; regras → erros HTTP
- Handoff SDD lista artefatos esperados (`architecture.md`, contrato, tasks)

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
.venv/bin/python -m src.run historia --dry-run   # → historia.md + PRD.md
.venv/bin/python -m src.run prd --dry-run        # só PRD.md
```

### Live (API)

`--live` está reservado para plugar clientes OpenAI/Claude em `src/reason.py` usando o JSON já montado em `outputs/llm_package_*.json`. Hoje levanta `NotImplementedError` de propósito.

---

## Exemplos de uso

Os exemplos abaixo assumem que você está em `pipeline/` com o venv ativo (ou use o prefixo `.venv/bin/python`).

### 1. Quickstart com os insumos de exemplo

O repositório já traz `inputs/figma.json`, `inputs/regras.yaml` e docs de amostra.

```bash
# História técnica + PRD (insumo para SDD)
.venv/bin/python -m src.run historia --dry-run

# Ver saídas
ls outputs/historia.md outputs/PRD.md
head -40 outputs/PRD.md
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
cp ~/Downloads/spec-produto.docx inputs/

# 2) Rode o artefato desejado
.venv/bin/python -m src.run historia --dry-run

# 3) Encaminhe o PRD ao estágio SDD
cp outputs/PRD.md ../sdd/inbox/PRD.md
```

Formato mínimo de `figma.json` e `regras.yaml`: ver seção [Insumos suportados](#insumos-suportados).

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
├── templates/
│   ├── openapi.skeleton.yaml
│   ├── mermaid.skeleton.md
│   ├── historia.skeleton.md
│   └── prd.skeleton.md       # PRD → SDD (frontmatter + RF/AC)
├── inputs/                   # corpus da execução (Figma, regras, docs)
├── state/                    # estado externo (sem histórico/docs brutos)
├── outputs/                  # artefatos + PRD.md + llm_package_*.json
└── src/
    ├── run.py                # orquestra etapas; also_emit (historia→prd)
    ├── ingest.py             # carrega figma/regras/template
    ├── docs_ingest.py        # extrai texto de txt/md/docx/doc
    ├── preprocess.py         # desidrata UI/regras (pré-LLM)
    ├── state_store.py        # persiste estado mínimo em JSON
    ├── doc_compress.py       # compressão hierárquica + SIGNAL_RE
    ├── rag_compress.py       # retrieve estrutural + merge UI/regras/docs
    ├── context_builder.py    # system + dynamic ≤ budget
    ├── reason.py             # pacote OpenAI/Claude + dry-run (inclui PRD)
    └── emit.py               # mapeia tipo → arquivo em outputs/
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

- Python 3.9+
- `PyYAML`
- `python-docx` (`.docx`)
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
5. Consumidor SDD que leia `outputs/PRD.md` (frontmatter `sdd.expected`) e gere architecture/tasks

---

## Lição de design

> Sistemas LLM em produção funcionam melhor quando o modelo vê a **informação certa**, não a **maior quantidade** de informação.

O **Prompt-less** aplica isso ao domínio de artefatos de tech lead: Figma, regras e documentos longos viram um contexto pequeno, estável e auditável — pronto para gerar OpenAPI, Mermaid, histórias e **PRD para SDD** com custo previsível.
