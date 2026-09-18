# 26-hybrid-document-retrieval

**Kanban:** Todo  
**Blocked by:** 19-contextual-provenance (Done), 23-candidate-evals (Done)

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

    40|- [ ] detecção de estrutura classifica o insumo (`structured` | `flat`) com evidência (nº de títulos, densidade de sinal)
- [ ] insumo `structured` usa âncoras de seção (reaproveitar `doc_preface.parse_sections`) como unidade de recuperação
- [ ] insumo `flat` mantém o caminho atual de `doc_compress` sem regressão
- [ ] recuperação estrutural/lexical barata permanece a **primeira** camada
- [ ] segunda camada semântica é opcional e limitada por budget
- [ ] todo trecho recuperado carrega `SourceRef` e `score` por estratégia
- [ ] deduplicação preserva diversidade de fontes
- [ ] golden fixtures medem recall e precisão (inclui doc com sinônimo e doc só narrativo)
- [ ] secrets/PII removidos antes de embeddings ou LLM
- [ ] fallback local funciona sem provider externo
    50|- [ ] custo adicional aparece na telemetria
- [ ] índice invertido por seção não entra no prompt (fica em `state/`, como `repo_index`)

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

_(preencher ao mover para Feedback)_
