# 27-sdd-consumer

**Kanban:** Done  
**Blocked by:** 08-ir-openapi-mermaid (Done), 22-code-evidence-spec (Done)

> Aprovado e **Done** em 2026-09-18. Riscos residuais aceitos (não reabrir
> a worktree filha). Mergeada no pai `.worktrees/onda-merge`
> (`feature/onda-frontier` `f29dde8`). PR do pai contra `main`:
> [#17](https://github.com/ilaraca/prompt-less/pull/17). Não abrir PR desta
> filha. O `28` ficou sem blocker aberto; issue local em
> `.scratch/harness/issues/28-engineering-baseline-v2.md`. Basear o 28 no
> pai (depois do merge do #17), não na worktree isolada desta filha.

Liberado em 2026-09-18 pelo Done do `22`. Fonte de escopo:
`pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `27-sdd-consumer`.

O `29-operations-por-contexto` (Done) já fatia operations no IR — o pacote SDD
lê o mesmo conjunto, não reimplementa o recorte. O `28` ficou liberado por
este Done. Nenhuma task vai a executor aqui (`10` / `14`).

## Comportamento entregue

O Canonical Spec/PRD gera um pacote SDD com arquitetura, contratos e tarefas
rastreáveis, pronto para revisão humana.

## Aceite

- [x] consumidor lê Canonical Spec como fonte principal
- [x] gera architecture, API decisions e tasks
- [x] cada task referencia RF, AC, NFR, serviço e evidência
- [x] dependências entre tasks reutilizam o grafo multi-repo
- [x] unresolved questions bloqueiam tasks afetadas
- [x] saída passa por schema validation
- [x] nenhuma task é enviada a executor antes de revisão

## Métrica de sucesso

- 100% das tasks ligadas a pelo menos um RF/AC;
- zero decisão crítica criada apenas pelo renderer;
- perguntas abertas bloqueiam apenas o escopo afetado.

## Implementation note

Worktree **filha** `.worktrees/27-sdd-consumer`, branch `feature/sdd-consumer`,
base 22 + merge 29 (`1a352c7`). HEAD `8317275`. Sem remote próprio — esperado.
Mergeada no pai `.worktrees/onda-merge` (`feature/onda-frontier` `f29dde8`).
PR do pai contra `main`: [#17](https://github.com/ilaraca/prompt-less/pull/17).
Não reabrir a filha nem abrir PR dela contra `main`.

O README da filha ainda lista “tokenizer é `len/4`” — limitação do slice na
base antiga; na `main`/pai o `12a` já saiu. Não rebasear a filha por isso.

Shipou o consumidor SDD que lê o Canonical Spec (`contract_operations()`) e
emite `sdd-package.yaml`: architecture, api_decisions e tasks rastreáveis.
Não refatia operations (29). Não classifica NFR por tipo (28). Não despacha
executor (10) nem apply/rollback (14).

**Como verificar**

```bash
cd .worktrees/onda-merge
PYTHONPATH=. ../pipeline/.venv/bin/python -m pytest tests/integration/test_sdd_consumer.py -q
PYTHONPATH=. ../pipeline/.venv/bin/python -m src.run sdd --dry-run --no-split
# → artifacts/sdd-package.yaml com source: canonical-spec, executor_dispatch: false
```

Suíte completa no pai: **253 passed**.

**O que saiu**

- `src/renderers/sdd.py` — pacote a partir do IR + `build_implementation_plan`
- `validate_sdd_package` / `config/sdd-package.schema.yaml` — gate fail-closed
- `run sdd`; `historia`/`prd` também emitem o pacote (`also_emit`)
- Tasks: RF+AC obrigatórios, NFR/serviço/evidência no registro; `depends_on`
  copia o grafo; pergunta `blocking` só nas operations do recorte

**Riscos residuais**

1. **Grafo observado convive no pai.** O `24` entrou na mesma onda (PR #17).
   A filha isolada do 27 ainda descreve tokenizer `len/4` e grafo heurístico
   — recorte do slice na base antiga; não rebasear a filha por isso.
2. **Spec com `open_questions.blocking=True`** continua bloqueando o pipeline
   inteiro em `validate_spec` (ambiguidade HTTP); o recorte fino vale no pacote
   SDD quando o spec chega ao renderer.
3. **Sem repos no IR**, cai numa task `TASK-APP-01` do serviço.
4. **Filha permanece no HEAD do slice.** Convívio com 15/21/25 e tokenizer
   oficial está no pai (`f29dde8` / PR #17). Não rebasear nem abrir PR da
   filha.

> Código no pai (PR #17). Só chega em `main` quando esse PR merjar.
> Não rebasear nem reabrir o worktree.
