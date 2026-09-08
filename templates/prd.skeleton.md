---
# Frontmatter consumível por SDD (Spec-Driven Development)
id: "{{prd_id}}"
title: "{{titulo}}"
status: draft
source: prompt-less
artifacts:
  historia: outputs/historia.md
  openapi: outputs/openapi.yaml
  sequence: outputs/sequence.mmd
  prd: outputs/PRD.md
sdd:
  expected:
    - architecture.md
    - sequence_refined.mmd
    - api_contract.yaml
    - tasks.md
---

# PRD — {{titulo}}

## 1. Problema
{{problema}}

## 2. Objetivo
{{objetivo}}

## 3. Fora de escopo (non-goals)
{{non_goals}}

## 4. Personas / usuários
{{personas}}

## 5. Escopo
### Inclui
{{escopo_in}}

### Não inclui
{{escopo_out}}

## 6. Requisitos funcionais
{{requisitos_funcionais}}

## 7. Contrato de dados (UI → API)
### Entrada (request)
{{dados_entrada}}

### Saída (response / lista)
{{dados_saida}}

### Ações
{{acoes}}

## 8. Regras de negócio e erros
{{regras_negocio}}

## 9. Critérios de aceite (BDD)
> Espelho das histórias técnicas; SDD deve preservar rastreabilidade.

{{criterios_bdd}}

## 10. Dependências
{{dependencias}}

## 11. Métricas de sucesso
{{metricas}}

## 12. Riscos e abertos
{{riscos}}

## 13. Handoff para SDD
O SDD deve consumir este PRD + artefatos linkados no frontmatter e produzir:

1. Arquitetura alvo (BFF / MFE / API de Domínio)
2. Sequência refinada (happy path + `alt`/`opt` das regras)
3. Contrato OpenAPI alinhado às seções 7–8
4. Breakdown de tasks com rastreio `RF-xx` / `AC-xx`

### Contexto comprimido (Prompt-less)
{{contexto_comprimido}}
