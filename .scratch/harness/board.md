# Board — Prompt-less Engineering Harness

Fonte: `docs/analise-engenheria-harness` + gaps pós-série 01–07 +
`docs/propostas-melhoria-limites-atuais.md` (§5, §6, §7).

## Série 1 — Fundação (concluída)

| ID | Título | Kanban | Blocked by |
|----|--------|--------|------------|
| 01-baseline-evals | Baseline de avaliações | Done | — |
| 02-runtime-execucao | Runtime por execução (run_id) | Done | 01 |
| 03-provenance-claims | Provenance e claims | Done | 02 |
| 04-spec-canonica | Spec canônica verificável | Done | 03 |
| 05-ciclo-executor | Ciclo fechado com executor | Done | 04 |
| 06-multi-repo | Multi-repositório coordenado | Done | 05 |
| 07-autoaperfeicoamento | Autoaperfeiçoamento | Done | 05 |

## Série 2 — Gaps

Blockers **rebloqueados pela §5** do documento de propostas (decisão humana de
2026-09-17, aceita integral). As dependências abaixo já refletem os novos IDs.

| ID | Título | Kanban | Blocked by |
|----|--------|--------|------------|
| 08-ir-openapi-mermaid | IR → OpenAPI / Mermaid | **Done** | 04 |
| 09-live-llm | Modo `--live` (OpenAI/Claude) | Todo | 08, 15, 18, 19 |
| 10-devin-e2e | Devin CLI real no close_loop | Todo | 09, 20, 21 |
| 11-stages-yaml | Orquestração via pipeline.yaml | **Done** | 18 |
| 12-ci-tokenizer-redis | CI no GitHub Actions (parte entregue) | **Done** | 01, 02 |
| 12a-official-tokenizer | Tokenizer oficial por provider | **Done** | 01, 02 |
| 12b-state-backend-redis | Backend de state em Redis | Todo ⏸ despriorizado | 02 |
| 13-parallel-exec | Execução concorrente por ondas | Todo | 10, 12b, 18, 24 |
| 14-apply-rollback | Apply de propostas + rollback | Todo | 21, 23 |
| 15-hardening-deep | Debugger, injection, recovery, golden recall | **Done** | 03, 08, 11 |
| 16-hardening-review | Hotfix review (policy, evals, provenance) | Done | — |
| 17-path-evals-claims | Path traversal + evals por camada + claims | Done | 16 |

### 12 dividido e despriorizado — decisão e riscos aceitos

Decisão humana (2026-09-17): **não mexer com infra (Redis/AWS) agora**, mas a §5 é
seguida e o ticket é dividido, para que a parte que *não* é infra não seja arrastada
junto. O `12` sai de `In progress`:

- `12` → **Done** em 2026-09-18, cobrindo só o que já foi entregue e merjado: o
  workflow `.github/workflows/ci.yml` rodando `pytest` (PR #1, commit `1abe628`).
  Não reabre o worktree.
- `12a-official-tokenizer` → **Done** em 2026-09-18. Não é infra, é biblioteca.
  Entrou em `main` no PR #15. Riscos residuais aceitos (Anthropic/Gemini
  heurísticos; encoding tiktoken no CI; clip de consolidado ainda em caracteres).
- `12b-state-backend-redis` → **Todo ⏸ parqueado**. É a parte de infra. Nenhum agente
  trabalha nela.
- endurecimento geral de CI → migra para `25-production-quality-gates` pela §5.

Riscos aceitos, com as mitigações já aplicadas:

1. **Tokenizer não podia ser parqueado junto.** Sem tokenizer oficial, budget e
   telemetria seguem em `chars/4` heurístico, e a §5 exige registrar
   `method=official|heuristic` e nunca apresentar fallback como contagem exata. É
   pré-requisito honesto do `09-live-llm`. *Mitigado:* virou `12a`, agora **Done**.
   O `09` ficou sem blocker aberto (15 Done).
2. **`13-parallel-exec` podia congelar pelo Redis.** A §7 faz `13` depender de `12b`;
   com `12b` parqueado, `13` ficaria preso por uma causa em outro ticket. *Mitigado:* o
   requisito real de `13` é a **interface de state com compare-and-set/lock**,
   entregável sobre o file backend sem Redis — registrado na issue do `12b`, para
   dividir de novo se `13` chegar antes da decisão mudar.
3. **Endurecimento geral de CI.** O `25` foi **Done** em 2026-09-18 (PR #15).
   O CI remoto não é mais só `pytest` (compile, ruff, mypy, coverage,
   pip-audit, secrets, YAML; matriz 3.10–3.13). Branch protection ainda **não**
   está ligada (`protected: false`) — residual aceito; ligar a regra é setting
   GitHub, não retrabalho.
4. **Retomada por outro worker permanece não testada.** Toda run assume worker único.
   Consequência aceita enquanto não houver execução concorrente real.

## Série 3 — Propostas

Derivada de `docs/propostas-melhoria-limites-atuais.md` (§6 e §7). Issues detalhadas:
`18`, `19`, `20`, `21`, `22`, `23`, `24`, `25`, `26`, `27`, `28` e `29`.

| ID | Título | Kanban | Blocked by |
|----|--------|--------|------------|
| 18-safe-run-storage | Escrita segura e atômica da run | **Done** | 02 |
| 19-contextual-provenance | Provenance por contexto, sem colisão | **Done** | 18 |
| 20-evidence-backed-verification | Verificação por evidência real | **Done** | 18, 19 |
| 21-auditable-approval | Aprovação auditável e vinculada | **Done** | 20 |
| 22-code-evidence-spec | Estado atual e gaps no spec | **Done** | 19 |
| 23-candidate-evals | Evals com candidato real | **Done** | 18, 22 |
| 24-evidence-based-planning | Plano por dependência observada | **Done** | 22 |
| 25-production-quality-gates | Gates mínimos de produção | **Done** | 18, 20 |
| 26-hybrid-document-retrieval | Recuperação híbrida de documentos | Todo | 19, 23 |
| 27-sdd-consumer | Pacote SDD a partir do IR | **Done** | 08, 22 |
| 28-engineering-baseline-v2 | NFR por tipo e criticidade | Todo | 22, 27 |
| 29-operations-por-contexto | Recorte de operations por serviço | **Done** | 08 |

### Frontier atual

`origin/main` em 2026-09-18: `d574634` (PR
[#16](https://github.com/ilaraca/prompt-less/pull/16)). Aberto:
[#17](https://github.com/ilaraca/prompt-less/pull/17) (24 + 27 no pai
`f29dde8`). Já na `main`: 08, 11, 12a, 15, 18, 19, 20, 21, 22, 23, 25 e
29. O [#15](https://github.com/ilaraca/prompt-less/pull/15) entrou antes
(`e9bdd91`).

`08`, `18` e `19` aprovados e `Done` em 2026-09-17 (19 entrou na `main` pela
onda, não pelo PR [#9](https://github.com/ilaraca/prompt-less/pull/9),
fechado).

`11-stages-yaml` aprovado e **Done** em 2026-09-18. Riscos residuais aceitos
(timeout best-effort; `--resume` reexecuta estágios idempotentes e não reabre
`completed`/`blocked`; `repos_scan`/`repo_index`/`marcar` desligados no default).
Detalhe na issue. Não reabre o worktree.

`20-evidence-backed-verification` aprovado e **Done** em 2026-09-18. Riscos
residuais aceitos (adapter Devin stub; worktree sujo vs `result_commit`; HMAC
nulo sem `PROMPTLESS_INTEGRITY_KEY`). Detalhe na issue. Não reabre o worktree.
Herdado pelo `10` (JSONL + worktree limpo) e pelo `21` (selo da aprovação,
Done em 2026-09-18).

`29-operations-por-contexto` aprovado e **Done** em 2026-09-18. Riscos
residuais aceitos (401 omitido pelo pré-filtro de regras no `--all-contexts`;
schemas de input/coluna globais na UI; `--context` com uma ação + um 2xx
resolve `200`). Detalhe na issue. Não reabre o worktree. `27` ficou
desbloqueado pelo Done do `22` e foi **Done** em 2026-09-18 (08 já era Done).

`21-auditable-approval` aprovado e **Done** em 2026-09-18. Riscos
residuais aceitos (promote é selo, não apply; binding aos arquivos da run,
não a um segundo `git diff`; ledger HMAC não é JSONL append-only;
`evidence_hashes.hmac` do 20 continua opcional; `execution.approved` no
payload não promove). Detalhe na issue. Não reabre o worktree. `10` ainda
espera `09`. `14` e `26` desbloqueados pelo Done do `23`.

`12`, `12a` e `22` aprovados e **Done** em 2026-09-18. Não reabrem worktree.
Riscos residuais do `22` aceitos (path único no matching; `status=NNN` →
`extra_in_code` heurístico; índice só com mapa/serviço / `no_split` de
propósito). Riscos residuais do `12a` aceitos (Anthropic/Gemini heurísticos).

Onda da frontier:

- `15` e `25` aprovados e **Done** em 2026-09-18. Riscos residuais aceitos
  (15: timeout best-effort, scan heurístico; 25: `main` `protected: false`).
  Não reabrem worktree filha. `09-live-llm` ficou **sem blocker aberto**.
- `23-candidate-evals` aprovado e **Done** em 2026-09-18. Entrou no pai
  e na `main` pelo PR [#16](https://github.com/ilaraca/prompt-less/pull/16)
  (`279267f` / merge `d574634`). Não reabre a filha. Riscos residuais
  aceitos (overlay ainda não é lido por `src.run` — efeito no IR é o `14`;
  `two_services` segue com 401 omitido — o gate multi-contexto que passa
  é `eval_multi_context`; suíte default maior). Detalhe na issue. `14` e
  `26` ficaram **sem blocker aberto**.
- `24` e `27` aprovados e **Done** em 2026-09-18. Entraram no pai
  (`f29dde8`); PR [#17](https://github.com/ilaraca/prompt-less/pull/17).
  Não reabrem as filhas. Sem remote próprio. Riscos residuais aceitos
  (24: matcher conservador, regex de import/evento, `coordenacao` é rótulo;
  27: não classifica NFR por tipo — o `28`; sem despacho a executor).
  Detalhe nas issues. `13` espera `10` e `12b`. `28` ficou **sem blocker
  aberto** (basear no pai depois do merge do #17).

Nada em **In progress**. Nada em **Feedback**. `12b` permanece parqueado.

| Ticket | Kanban | Papel | Onde está o código |
|---|---|---|---|
| 09-live-llm | **Todo** (frontier) | filha a criar | base: `origin/main` (`d574634`) |
| 14-apply-rollback | **Todo** (frontier) | filha a criar | overlay no `run`; `main` já tem o 23 |
| 26-hybrid-document-retrieval | **Todo** (frontier) | filha a criar | eval diferencial do 23; overlay no IR continua no `14` |
| 28-engineering-baseline-v2 | **Todo** (frontier) | filha a criar | espera o merge do PR #17; não basear na worktree isolada do 27 |
| 24-evidence-based-planning | **Done** (no pai) | filha, HEAD `2a26f44` | pai `f29dde8` · PR [#17](https://github.com/ilaraca/prompt-less/pull/17) |
| 27-sdd-consumer | **Done** (no pai) | filha, HEAD `8317275` | pai `f29dde8` · PR [#17](https://github.com/ilaraca/prompt-less/pull/17) |
| (pai) onda-frontier | — | integra filhas; único PR contra `main` | `.worktrees/onda-merge` · `feature/onda-frontier` `f29dde8` · PR [#17](https://github.com/ilaraca/prompt-less/pull/17) |

Um agente/branch por ticket, em paralelo (§8 Onda C + restante da Onda B).

`11` voltou à frontier depois do Done do `18` e foi aprovado em 2026-09-18.
`15` e `25` aprovados em 2026-09-18. `09` é a frontier da série 2 restante.
`14` e `26` voltaram à frontier com o Done do `23` (promote do `21` é selo;
o `14` é quem aplica config e lê o overlay). `28` entrou na frontier com
o Done do `27`.

## Dependências (visão)

```
02 Done
  └─► 18 safe run/storage Done
       ├─► 19 provenance contextual Done
       │    ├─► 22 evidência de código no spec Done
       │    │    ├─► 23 evals com candidato real Done
       │    │    │    ├─► 14 apply + rollback
       │    │    │    └─► 26 recuperação híbrida
       │    │    ├─► 24 planejamento por evidência Done
       │    │    │    └─► 13 execução paralela
       │    │    └─► 27 consumidor SDD Done
       │    │         └─► 28 baseline engenharia v2
       │    └─► 20 verificação por evidência Done
       │         ├─► 21 aprovação auditável Done
       │         │    ├─► 10 Devin E2E
       │         │    └─► 14 apply + rollback
       │         └─► 25 gates de produção Done
       ├─► 11 stages YAML Done
       └─► 12b state backend Redis ⏸ (despriorizado)

04 Done ─► 08 IR (Canonical Spec) → OpenAPI/Mermaid ─► 29 operations por contexto
08 + 15 Done + 18 + 19 ─► 09 live LLM
09 + 20 + 21 ─► 10 Devin E2E
10 + 12b + 18 + 24 Done ─► 13 execução paralela

01 + 02 Done ─► 12a tokenizer oficial Done (pré-requisito do 09; 15 Done)
```

## Versionamento

Um repositório: **`ilaraca/prompt-less`** (`origin`).

- **Código + governança** no mesmo git. Este board, `issues/` e os docs de
  análise/correções estão em `.scratch/harness/` e `docs/`.
- **Editar Kanban só em** `pipeline/.scratch/harness/` (pasta real no
  clone; sem cópia/symlink na raiz do workspace).
  Nunca em `.worktrees/**/.scratch/harness/`.
- Clone canônico do workspace: `pipeline/` na branch `workspace/stable`
  (rastreia `origin/feature/onda-frontier` até a onda mergiar; depois `main`).
- Checagem: `bash scripts/check_kanban_sync.sh` em `pipeline/`.
- A pasta-mãe `techlead-docs` é só workspace Cursor; não é repositório git.

Implementação de ticket acontece em **worktree filha** em
`.worktrees/<id-slug>/` (fora do tree do clone), numa branch `feature/<slug>`.
Essas filhas **não** abrem PR contra `main`. Quem integra é o pai
`.worktrees/onda-merge` (`feature/onda-frontier`): merge das filhas da onda,
um único PR. A filha permanece no HEAD do slice; ficar “atrás da `main`”
depois do merge do pai é esperado — não rebasear a filha nem reabrir o
worktree. Filha sem remote próprio também é esperado (15/25 tiveram remote
só porque PRs empilhados #13/#14 existiram e foram fechados em favor do #15).

Ferramenta de apoio entregue fora do Kanban: `src/doc_preface.py` (índice de salto para
documentos longos), na branch `feature/doc-jump-index`.

Detalhe série 1: issues em `.scratch/harness/issues/01–07*`  
Detalhe série 2: `spec-serie-2.md` + `issues/08–15*`, incluindo `issues/12a-official-tokenizer.md`
e `issues/12b-state-backend-redis.md`  
Detalhe série 3: `docs/propostas-melhoria-limites-atuais.md` (prefácio no topo tem
âncoras por ticket) + `.scratch/harness/issues/18-safe-run-storage.md` + `issues/19-contextual-provenance.md` + `issues/20-evidence-backed-verification.md` + `issues/21-auditable-approval.md`
+ `issues/22-code-evidence-spec.md` + `issues/23-candidate-evals.md` + `issues/24-evidence-based-planning.md` + `issues/25-production-quality-gates.md`
+ `issues/26-hybrid-document-retrieval.md` + `issues/27-sdd-consumer.md` + `issues/28-engineering-baseline-v2.md` + `issues/29-operations-por-contexto.md`
