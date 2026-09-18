# 13-parallel-exec

**Kanban:** Todo  
**Blocked by:** 10-devin-e2e, 12b-state-backend-redis (⏸ despriorizado), 18-safe-run-storage (Done), 24-evidence-based-planning (Done)

> `12b` está parqueado por decisão humana (não mexer com infra agora). Se este ticket
> chegar na frontier antes de a decisão mudar, **não espere o Redis**: o requisito real
> aqui é a interface de state com compare-and-set/lock, entregável sobre o file backend.
> Ver a seção de risco na issue do `12b`.
>
> O `24` foi **Done** em 2026-09-18 e entrou no pai (PR
> [#17](https://github.com/ilaraca/prompt-less/pull/17)). Este ticket
> continua bloqueado por `10` e `12b`. Não reabrir a filha do 24.

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
