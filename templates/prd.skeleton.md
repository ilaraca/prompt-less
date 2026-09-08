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
  engenharia: inputs/engenharia.yaml
  mapa_servicos: inputs/mapa-servicos.yaml
ownership:
  service_id: "{{service_id}}"
  service_name: "{{service_nome}}"
  repos: {{repos_yaml}}
sdd:
  expected:
    - architecture.md
    - sequence_refined.mmd
    - api_contract.yaml
    - tasks.md
  nfr_ids:
    - NFR-R
    - NFR-O
    - NFR-S
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

## 10. Requisitos não-funcionais (baseline v1)
> Fonte: `inputs/engenharia.yaml`. Expandir em versões futuras (circuit breaker, metrics, tracing…).

### Stack e arquitetura
{{nfr_stack_arch}}

### Resiliência (`NFR-R`)
{{nfr_resiliencia}}

### Observabilidade (`NFR-O`)
{{nfr_observabilidade}}

### Segurança mínima (`NFR-S`)
{{nfr_seguranca}}

## 11. Dependências
{{dependencias}}

## 12. Métricas de sucesso
{{metricas}}

## 13. Riscos e abertos
{{riscos}}

## 14. Handoff para SDD
O SDD deve consumir este PRD + artefatos linkados no frontmatter e produzir:

1. Arquitetura alvo (BFF / MFE / API de Domínio) alinhada à seção 10
2. Sequência refinada (happy path + `alt`/`opt` das regras)
3. Contrato OpenAPI alinhado às seções 7–8
4. Breakdown de tasks com rastreio `RF-xx` / `AC-xx` / `NFR-R|O|S-xx`

### Contexto comprimido (Prompt-less)
{{contexto_comprimido}}
