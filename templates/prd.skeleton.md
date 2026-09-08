---
# Frontmatter consumível por SDD (Spec-Driven Development)
id: "{{prd_id}}"
title: "{{titulo}}"
status: draft
source: prompt-less
artifacts:
  historia: {{artifacts_dir}}/historia.md
  openapi: {{artifacts_dir}}/openapi.yaml
  sequence: {{artifacts_dir}}/sequence.mmd
  prd: {{artifacts_dir}}/PRD.md
  engenharia: inputs/engenharia.yaml
  mapa_servicos: inputs/mapa-servicos.yaml
ownership:
  service_id: "{{service_id}}"
  service_name: "{{service_nome}}"
  repos: {{repos_yaml}}
  camadas: {{camadas_yaml}}
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

## 11. Estado atual do código (baseline verificável)
> Evidência estática de `state/repo_index.json` — rotas, entidades e códigos HTTP
> que já existem nos repos deste serviço. Não é inferência de LLM.

{{estado_atual}}

### Gaps entre requisito e código
{{gaps}}

## 12. Dependências
{{dependencias}}

## 13. Métricas de sucesso
{{metricas}}

## 14. Riscos e abertos
{{riscos}}

## 15. Handoff para SDD
O SDD deve consumir este PRD + artefatos linkados no frontmatter e produzir:

1. Arquitetura alvo (BFF / MFE / API de Domínio) alinhada às seções 10–11
2. Sequência refinada (happy path + `alt`/`opt` das regras)
3. Contrato OpenAPI alinhado às seções 7–8
4. Breakdown de tasks com rastreio `RF-xx` / `AC-xx` / `NFR-R|O|S-xx`

### Contexto comprimido (Prompt-less)
{{contexto_comprimido}}
