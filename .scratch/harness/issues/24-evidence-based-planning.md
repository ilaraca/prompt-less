# 24-evidence-based-planning

**Kanban:** Done  
**Blocked by:** 22-code-evidence-spec (Done)

> Aprovado e **Done** em 2026-09-18. Riscos residuais aceitos (não reabrir
> a worktree filha). Mergeada no pai `.worktrees/onda-merge`
> (`feature/onda-frontier` `f29dde8`). PR do pai contra `main`:
> [#17](https://github.com/ilaraca/prompt-less/pull/17). Não abrir PR desta
> filha. O `13` fica sem este blocker; continua à espera de `10` e `12b`.

Liberado em 2026-09-18 pelo Done do `22`. Fonte de escopo:
`pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `24-evidence-based-planning`.

O plano multi-repo (`src/plan_repos.py`, `src/planning/`) já usa topologia por
camada (`src/planning/layers.py`). Este ticket troca a autoridade: dependência
**observada** no código/contratos; a camada fica fallback revisável. Apoiar-se
em `repo_index` e `code_evidence` do 22. Não implementar execução paralela (`13`).

## Comportamento entregue

O plano multi-repo usa dependências observadas no código e contratos, mantendo a
topologia por camada apenas como fallback revisável.

## Aceite

- [x] dependências possuem `from`, `to`, tipo, arquivo/símbolo e confiança
- [x] OpenAPI clients, imports, URLs, eventos e build files alimentam o grafo
- [x] grafo global detecta repositórios compartilhados e ciclos
- [x] fallback heurístico é marcado e exige revisão
- [x] contratos produzidos/consumidos derivam do Canonical Spec
- [x] `ready_for_parallel_execution` exige plano revisado e ausência de conflito
- [x] implementação plan registra por que cada dependência existe

## Métrica de sucesso

- nenhuma aresta observada sem evidência;
- nenhuma tarefa paralela compartilha workspace/repositório sem coordenação;
- ciclos e dependências ausentes bloqueiam o scheduler.

## Implementation note

Worktree **filha** `.worktrees/24-evidence-based-planning`, branch
`feature/evidence-based-planning`, base `feature/code-evidence-spec` (`5c31c4e`).
HEAD `2a26f44`. Sem remote próprio — esperado. Mergeada no pai
`.worktrees/onda-merge` (`feature/onda-frontier` `f29dde8`). PR do pai
contra `main`: [#17](https://github.com/ilaraca/prompt-less/pull/17).
Não reabrir a filha nem abrir PR dela contra `main`.

README + CHANGELOG da filha descrevem o caminho feliz; os limites do matcher
estão só nesta issue (não há seção `Riscos aceitos` no CHANGELOG).

> Código no pai (PR #17). Só chega em `main` quando esse PR merjar.
> Não rebasear nem reabrir o worktree.

Shipou plano multi-repo cuja autoridade é dependência **observada**
(OpenAPI client, import, URL, evento, build file e contratos do Canonical Spec).
Cada aresta tem `from`/`to`, tipo, arquivo/símbolo, confiança e `reason`.
Camada fica `origin: heuristic` + `requires_review`. Grafo global marca
repos compartilhados (exige `coordenacao` no mapa) e ciclos; contratos `spec:`
ausentes e ciclos esvaziam as ondas / bloqueiam
`ready_for_parallel_execution` até `--reviewed` e sem conflito. Execução
concorrente (`13`) não foi implementada.

### Commits

| Hash | Mensagem |
|---|---|
| `33f0071` | feat: ancora o plano multi-repo em dependências observadas |
| `e4d8d04` | test: cobre grafo observado, fallback heurístico e bloqueio do scheduler |
| `2a26f44` | docs: documenta plano multi-repo baseado em evidência observada |

### Arquivos

`src/planning/dependencies.py`, `src/planning/graph.py`, `src/planning/plan.py`,
`src/plan_repos.py`, `src/repo_index.py`,
`tests/integration/test_multi_repo_plan.py`, `README.md`, `CHANGELOG.md`.

### Como verificar

```bash
cd ".worktrees/onda-merge"
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
```

Esperado: **253 passed** (pai com 24 + 27). Filha isolada: 125.

### Riscos residuais

Não furam o aceite. O slice pede evidência na aresta observada e fallback
marcado — não matching perfeito de todo import do mundo.

1. **Resolver alvo é conservador.** Só casa nome completo do repo (ou forma
   compacta com ≥8 chars). Alias curto compartilhado (`ofertas` em
   `ofertas-api` e `ofertas-bff`) **não** vira aresta — evita falso positivo;
   pode deixar de ligar um client genérico (`@FeignClient("ofertas")`).
   Endurecer com dicionário de aliases no mapa é polimento, não retrabalho.

2. **Regex de import/evento é ruidoso.** Muitos hits ficam no índice; só viram
   aresta se o alvo resolver para um repo único. `.send("...")` pode colher
   HTTP se o tópico coincidir. A métrica era “nenhuma aresta observed sem
   evidência”, não “zero sinal extra no índice”.

3. **`coordenacao` no mapa é rótulo.** Declara que o repo compartilhado está
   coordenado; não implementa lock nem execução paralela (`13`). Sem o campo,
   o relatório marca conflito e `ready_for_parallel_execution` fica falso.

4. **Filha permanece no HEAD do slice.** Convívio com hardening/gates/
   tokenizer/operations está no pai (`f29dde8` / PR #17), não nesta worktree.
   Não rebasear a filha contra `main`.
