# 02-runtime-execucao

**Kanban:** Done  
**Blocked by:** 01-baseline-evals (Done)

## Objetivo

Introduzir `RunContext`, `run_id`, `manifest.json`, `events.jsonl` e `runs/<run_id>/` sem mudar a lógica funcional de geração.

## Aceite

- [x] `src/runtime/` com RunContext + event store
- [x] cada `run()` gera `run_id` e grava sob `runs/<run_id>/`
- [x] duas execuções não sobrescrevem seus estados
- [x] retorno JSON inclui `run_id` e `status`
- [x] cópia compatível em `outputs/` (Devin / scripts)
- [x] testes pytest cobrem isolamento

## Implementation note

Entregue em `feature/runtime-execucao-run-id`. Aceito para desbloquear 03.
