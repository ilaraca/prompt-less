# Spec longa de exemplo

## Glossário

| Sigla | Significado | Neste projeto |
|---|---|---|
| **IR** | Intermediate Representation | Canonical Spec |
| **PRD** | Product Requirements Document | Artefato da pipeline |

## 1. Regras de negócio

O bloqueio HTTP 403 ocorre quando o acesso é negado.
O endpoint POST /vitrine aplica o cupom na vitrine.

### 08-ir-openapi-mermaid

**Kanban:** Todo  
**Blocked by:** 04-spec-canonica (Done)

OpenAPI e Mermaid devem derivar do Canonical Spec. História e PRD já renderizam a partir do IR.

### 18-safe-run-storage

**Kanban:** Todo  
**Blocked by:** 02-runtime-execucao (Done)

Uma execução só escreve dentro de `runs/` e nunca deixa state parcial.

### 19-contextual-provenance

**Kanban:** Todo  
**Blocked by:** 18-safe-run-storage

Claims não colidem entre contextos. Provenance reconstitui a fonte.

### 22-code-evidence-spec

**Kanban:** Todo  
**Blocked by:** 19-contextual-provenance

História e PRD mostram o estado atual e os gaps reais do repositório.

#### Aceite

- Canonical Spec modela `current_state`, `gaps` e `code_evidence`.
- repo index aponta arquivo, símbolo, linha, rota e confiança.
