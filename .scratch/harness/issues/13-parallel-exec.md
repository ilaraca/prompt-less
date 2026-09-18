# 13-parallel-exec

**Kanban:** Todo  
**Blocked by:** 10-devin-e2e (**Done**), 12b-state-backend-redis (⏸ despriorizado — **não bloquear**), 18-safe-run-storage (Done), 24-evidence-based-planning (Done)

> `12b` está parqueado. **Não espere o Redis**: o requisito real é a
> interface de state com compare-and-set/lock no file backend. Ver risco
> na issue do `12b`.
>
> O `10` foi **Done** em 2026-09-18 (`dca477f`). Este ticket ficou
> **sem blocker aberto** (CAS no file backend). Não reabrir a filha do 10.

## Objetivo

Executar adapters por **onda** do `implementation_plan` com limite de paralelismo e relatório agregado.

## Aceite

- [ ] scheduler consome `waves` do plano
- [ ] N execuções concorrentes com semáforo configurável
- [ ] agregação de `ExecutionResult` + verify por repo
- [ ] falha numa task não apaga resultados das irmãs da onda
- [ ] testes com adapter fake paralelo

## Implementation note

_(preencher ao mover para Feedback)_
