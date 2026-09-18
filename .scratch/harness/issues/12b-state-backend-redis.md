# 12b-state-backend-redis

**Kanban:** Todo ⏸ despriorizado  
**Blocked by:** 02-runtime-execucao (Done)

> **Parqueado por decisão humana (2026-09-17):** não mexer com infra (Redis/AWS) agora.
> Nenhum agente trabalha neste ticket. Desmembrado de `12-ci-tokenizer-redis` pela §5.

## Comportamento entregue

Uma run pode ser retomada por outro worker sem perder consistência.

## Aceite

- [ ] interface comum para backend file e Redis
- [ ] file permanece default
- [ ] TTL configurável sem apagar run ativa
- [ ] compare-and-set ou lock de transição
- [ ] teste de dois workers concorrentes
- [ ] indisponibilidade do Redis falha sem corromper state

## Risco de parquear: não congelar o 13

A §7 faz `13-parallel-exec` depender deste ticket. Se `12b` ficar parqueado
indefinidamente, `13` fica preso por uma causa que está em outro ticket.

Mitigação registrada: o que `13` realmente precisa é da **interface de state com
compare-and-set/lock**, que é entregável sobre o file backend — os dois primeiros e o
quarto item do aceite acima, sem Redis. Se `13` chegar na frontier antes desta decisão
mudar, dividir este ticket mais uma vez em "interface + lock no file backend" (sem infra)
e "adapter Redis" (infra).

Consequência aceita enquanto isso: toda run assume worker único, e retomada por outro
worker permanece não testada.

## Implementation note

_(preencher ao mover para Feedback)_
