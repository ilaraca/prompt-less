# 28-engineering-baseline-v2

**Kanban:** Todo  
**Blocked by:** 22-code-evidence-spec (Done), 27-sdd-consumer (Done)

> Liberado em 2026-09-18 pelo Done do `27`. Worktree filha nova; base o pai
> `feature/onda-frontier` (PR [#17](https://github.com/ilaraca/prompt-less/pull/17))
> **depois** do merge em `origin/main` — o pacote SDD e o grafo observado
> já estão no pai. Não basear na worktree isolada do 27.
> Fonte: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
> âncora `28-engineering-baseline-v2`.

O `22` já modela estado atual e gaps no IR. O `27` emite `sdd-package.yaml`
com tasks que citam NFR, mas **não** classifica NFR por tipo nem por
criticidade. Este ticket é quem seleciona o baseline. Não despacha executor
(`10` / `14`).

## Objetivo

Cada serviço recebe NFRs proporcionais ao seu tipo e criticidade sem inflar
o prompt.

## Aceite

- [ ] `engenharia.yaml` versionado por schema
- [ ] suporte a circuit breaker, metrics, tracing, idempotência e segurança
- [ ] NFRs selecionados por contexto/camada, não enviados integralmente
- [ ] cada NFR tem origem `baseline|declared|observed`
- [ ] conflitos com o código atual geram gaps
- [ ] templates antigos continuam compatíveis por migração
- [ ] história, PRD e tasks SDD compartilham os mesmos IDs de NFR

## Métrica de sucesso

- NFRs críticos presentes nos serviços aplicáveis;
- aumento de contexto dentro do budget configurado;
- zero duplicação divergente entre história, PRD e tasks.

## Implementation note

_(preencher ao mover para Feedback)_
