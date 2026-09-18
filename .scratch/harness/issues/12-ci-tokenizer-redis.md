# 12-ci-tokenizer-redis

**Kanban:** Done  
**Blocked by:** 01-baseline-evals (Done), 02-runtime-execucao (Done)

> **Dividido pela §5** do documento de propostas, que aponta que este ticket misturava
> três comportamentos independentes. O ID `12` é preservado como registro histórico da
> parte que já foi entregue; o restante saiu para tickets próprios.

## Escopo original

CI no GitHub, contagem de tokens oficial e backend Redis opcional para state.

## Aceite

- [x] workflow `.github/workflows/ci.yml` rodando `pytest`
- [→] tokenizer pluggável (tiktoken e/ou equivalente); fallback `chars/4` → `12a-official-tokenizer`
- [→] `state.backend: redis` funcional com TTL documentado → `12b-state-backend-redis` (⏸ despriorizado)
- [→] file backend continua default → `12b-state-backend-redis`
- [→] teste de paridade aproximada heurística vs tokenizer → `12a-official-tokenizer`
- [→] endurecimento geral de CI (dependência, secrets, supply chain) → `25-production-quality-gates`

## Implementation note

**Entregue:** `.github/workflows/ci.yml` rodando `pytest` no GitHub Actions, merjado no
`origin/main` pelo PR #1 (commit `1abe628`, repo `ilaraca/prompt-less`).

**Como verificar:** `.venv/bin/python -m pytest -q` local (52 passando) e o workflow no
Actions do repositório.

**Restante:** nada pendente sob este ID. O tokenizer virou `12a-official-tokenizer`
(**Done** em 2026-09-18), o backend de state virou `12b-state-backend-redis` (parqueado
por decisão humana de não mexer com infra agora) e o endurecimento de CI foi para
`25-production-quality-gates` (In progress).

> Aprovado por humano em 2026-09-18. Não reabre o worktree.
