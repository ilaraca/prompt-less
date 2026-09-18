# 26-hybrid-document-retrieval

**Kanban:** Feedback  
**Blocked by:** 19-contextual-provenance (Done), 23-candidate-evals (Done)

> Worktree filha `.worktrees/26-hybrid-document-retrieval`, branch
> `feature/hybrid-document-retrieval`, base `origin/main` (`aaeb004`).

> O `19` e o `23` já saíram. O 23 tem workspaces distintos e gate por caso
> crítico; o overlay ainda **não** entra no `src.run` (residual aceito,
> fica no `14`). Retrieval pode usar a eval de candidato para provar que
> o recall subiu.

## Objetivo
    10|
Documentos de negócio com sinônimos, linguagem indireta ou estrutura incomum preservam
requisitos críticos sem enviar conteúdo bruto ao modelo. O retrieval passa a **escolher a
estratégia conforme a estrutura do insumo**, em vez de aplicar um filtro lexical único.

## Contexto: o que já existe

| Camada | Onde | O que faz |
|---|---|---|
| Chunk + sinal lexical | `src/doc_compress.py` | Fatia 40 linhas, filtra `SIGNAL_RE`, resume, emite `Claim` + `SourceRef`, registra descarte recuperável |
    20|| Retrieve estrutural | `src/rag_compress.py` | UI/regras/engenharia → chunks nomeados dentro do budget |
| De/para por serviço | `src/marcar.py` | Segmenta por títulos, pontua com IDF sobre vocabulário do código |
| Âncoras + índice invertido | `src/doc_preface.py` | Seções hierárquicas com linha inicial/final, TF-IDF termo → seção, grafo de tickets |

`doc_preface` foi escrito para navegação de **spec longa estruturada** por agente
(ver `docs/propostas-melhoria-limites-atuais.md`). Hoje **não está plugado** em nenhum
estágio da pipeline — e não deve ser antes deste ticket.

### Por que não basta reaproveitar as âncoras

    30|Medido em `inputs/amostra_3000.txt`: 2996 de 2999 linhas são `ruido de telemetria`, sem
um único título. O sinal real está isolado (regra de CPF na linha 100, `POST /clientes` na
500, permissão 403 na 2500). Nesse insumo, âncoras de seção não existem e a camada de
chunk + sinal continua sendo a correta.

Conclusão: âncoras servem documento **com estrutura**; chunk+sinal serve documento
**sem estrutura**. O ticket precisa de um roteador entre as duas, não de uma troca.

## Aceite

    40|- [x] detecção de estrutura classifica o insumo (`structured` | `flat`) com evidência (nº de títulos, densidade de sinal)
- [x] insumo `structured` usa âncoras de seção (reaproveitar `doc_preface.parse_sections`) como unidade de recuperação
- [x] insumo `flat` mantém o caminho atual de `doc_compress` sem regressão
- [x] recuperação estrutural/lexical barata permanece a **primeira** camada
- [x] segunda camada semântica é opcional e limitada por budget
- [x] todo trecho recuperado carrega `SourceRef` e `score` por estratégia
- [x] deduplicação preserva diversidade de fontes
- [x] golden fixtures medem recall e precisão (inclui doc com sinônimo e doc só narrativo)
- [x] secrets/PII removidos antes de embeddings ou LLM
- [x] fallback local funciona sem provider externo
    50|- [x] custo adicional aparece na telemetria
- [x] índice invertido por seção não entra no prompt (fica em `state/`, como `repo_index`)

## Métrica de sucesso

- aumento mensurável de recall nas golden fixtures;
- zero redução nos casos lexicais existentes;
- budget máximo respeitado;
- nenhum trecho sem provenance entra no Canonical Spec.

    60|## Escopo desta issue vs. `doc_preface`

`doc_preface` continua sendo ferramenta de **navegação do agente** sobre docs de roadmap
(`--apply`, `--lookup`, `--show`). Este ticket só reaproveita o *parser de seções* e a
*ponderação TF-IDF*; não promove o prefácio a estágio da pipeline nem coloca o índice
no contexto do modelo.

## Implementation note

Entregue na branch `feature/hybrid-document-retrieval`.

### O que saiu
- Roteador `structured` | `flat` em `src/hybrid_retrieval.py` com evidência
  (`heading_count`, `signal_density`)
- `structured` → âncoras via `doc_preface.parse_sections` + TF-IDF; índice
  invertido em `state/doc_section_index.json` (não no prompt)
- `flat` → caminho `doc_compress` (chunk + `SIGNAL_RE`) sem regressão
- 1ª camada sempre lexical/estrutural; 2ª semântica opcional com budget e
  fallback local (sinônimos + TF), sem provider externo
- Scrub de secrets/PII antes da camada semântica; cada hit com `SourceRef`,
  `score` e `retrieval_strategy`; dedupe com diversidade de fontes
- Telemetria: `est_tokens_semantic` + `hybrid` em `rag_stats`
- Plugado em `rag_compress` e handler `doc_compress`
- README + CHANGELOG `[Unreleased]` atualizados

### Como verificar
```bash
cd .worktrees/26-hybrid-document-retrieval
PYTHONPATH=. python scripts/quality_gates.py
PYTHONPATH=. python -m src.hybrid_retrieval tests/fixtures/hybrid_structured/spec.md --detect-only
PYTHONPATH=. python -m pytest tests/integration/test_hybrid_retrieval.py -q
```

### Riscos residuais
- Camada semântica é lexical expandida (não embeddings); sinônimos fora do
  léxico local ainda falham
- `doc_preface` CLI (`--apply`/`--lookup`) permanece ferramenta de navegação
  do agente — não é estágio da pipeline
- Overlay IR do 23 continua residual no 14
