# Board — Prompt-less Engineering Harness

Fonte: `docs/analise-engenheria-harness` + gaps pós-série 01–07 +
`docs/propostas-melhoria-limites-atuais.md` (§5, §6, §7) + revisão de conformidade
com `prompt-less-roadmap-harness(1).md` em 2026-09-18 (série 4).

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
| 09-live-llm | Modo `--live` (OpenAI/Claude) | **Done** | 08, 15, 18, 19 |
| 10-devin-e2e | Devin CLI real no close_loop | **Done** | 09, 20, 21 |
| 11-stages-yaml | Orquestração via pipeline.yaml | **Done** | 18 |
| 12-ci-tokenizer-redis | CI no GitHub Actions (parte entregue) | **Done** | 01, 02 |
| 12a-official-tokenizer | Tokenizer oficial por provider | **Done** | 01, 02 |
| 12b-state-backend-redis | Backend de state em Redis | Todo ⏸ despriorizado | 02 |
| 13-parallel-exec | Execução concorrente por ondas | **Done** | 10, 12b, 18, 24 |
| 14-apply-rollback | Apply de propostas + rollback | **Done** | 21, 23 |
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
| 26-hybrid-document-retrieval | Recuperação híbrida de documentos | **Done** | 19, 23 |
| 27-sdd-consumer | Pacote SDD a partir do IR | **Done** | 08, 22 |
| 28-engineering-baseline-v2 | NFR por tipo e criticidade | **Done** | 22, 27 |
| 29-operations-por-contexto | Recorte de operations por serviço | **Done** | 08 |

### Histórico da frontier — séries 1–3

`origin/main` em 2026-09-18: `aaeb004` (PR
[#17](https://github.com/ilaraca/prompt-less/pull/17) merged — 24 + 27).
Já na `main`: 08, 11, 12a, 15, 18, 19, 20, 21, 22, 23, 24, 25, 27 e 29.
O [#16](https://github.com/ilaraca/prompt-less/pull/16) (`d574634`) e o
[#15](https://github.com/ilaraca/prompt-less/pull/15) entraram antes.

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
- `24` e `27` aprovados e **Done** em 2026-09-18. Entraram na `main`
  pelo PR [#17](https://github.com/ilaraca/prompt-less/pull/17)
  (`aaeb004`). Não reabrem as filhas. Sem remote próprio. Riscos residuais
  aceitos (24: matcher conservador, regex de import/evento, `coordenacao`
  é rótulo; 27: não classifica NFR por tipo — o `28`; sem despacho a
  executor). Detalhe nas issues. `13` espera `10` e `12b`. `28` ficou
  **sem blocker aberto**.

Onda C aprovada e **Done** em 2026-09-18 (integração no pai
`feature/onda-frontier`). `10-devin-e2e` **Done** (Onda D). `12b`
permanece parqueado (futuro). `13` desbloqueado pelo Done do `10` —
implementar CAS/lock no file backend (sem Redis/`12b`).

Riscos residuais aceitos do `10` (não reabrir worktree filha):

| Ticket | HEAD | Residuais aceitos |
|---|---|---|
| `10-devin-e2e` | `60e9579` | Comandos internos da sessão Devin não vão sozinhos ao JSONL (sidecar `execution-result.json` necessário); `DEVIN_E2E=1` exige CLI autenticado (CI skipa); auto-commit só no checkout isolado (sem push/PR) |

Riscos residuais aceitos (não reabrir worktree filha):

| Ticket | HEAD | Residuais aceitos |
|---|---|---|
| `09-live-llm` | `af3e67b` | Gemini sem client; loop de tools limitado; IDs Anthropic pinned a snapshot; gate `derived_artifact` ainda bloqueia saída fora do IR; `cost_usd` = tabela local, não fatura do vendor |
| `14-apply-rollback` | `f9f2950` | Overlay/keys sem consumidor completo de negócio no IR (persistência + anti-regressão); jitter de `avg_latency_ms` não prova melhoria; `promote` continua só selo; suíte default de apply é a completa se `--cases` omitido |
| `26-hybrid-document-retrieval` | `5f5c447` | 2ª camada = sinônimos locais + TF (não embeddings); `doc_preface` CLI não é estágio da pipeline |
| `28-engineering-baseline-v2` | `5a2ddb2` | Sinais NFR no índice por substring (gaps `heuristic`); alertas/ADRs/bulkhead fora do catálogo v2; sem despacho a executor |

**Onda D** aprovada e **Done** em 2026-09-18 — HEAD `60e9579` em
`feature/devin-e2e` (PR [#19](https://github.com/ilaraca/prompt-less/pull/19)
merged). `12b` parqueado.

**Onda E** aprovada e **Done** em 2026-09-18 — HEAD `4175436` em
`feature/parallel-exec`. Frontier das séries 1–3 **encerrada** salvo
`12b-state-backend-redis` (Todo ⏸ parqueado — futuro).

Riscos residuais aceitos do `13` (não reabrir worktree filha):

| Ticket | HEAD | Residuais aceitos |
|---|---|---|
| `13-parallel-exec` | `4175436` | CLI sem Devin-por-task (`--stub` / adapter injetado); onda seguinte ainda roda após falha parcial; Redis/`12b` intocado |

| Ticket | Kanban | Papel | Onde está o código |
|---|---|---|---|
| 13-parallel-exec | **Done** | filha, HEAD `4175436` | `.worktrees/13-parallel-exec` · `feature/parallel-exec` |
| 12b-state-backend-redis | Todo ⏸ | parqueado | futuro |
| 10-devin-e2e | **Done** | filha, HEAD `60e9579` | `.worktrees/10-devin-e2e` · `feature/devin-e2e` |
| 09-live-llm | **Done** | filha, HEAD `af3e67b` | `.worktrees/09-live-llm` · `feature/live-llm` |
| 14-apply-rollback | **Done** | filha, HEAD `f9f2950` | `.worktrees/14-apply-rollback` · `feature/apply-rollback` |
| 26-hybrid-document-retrieval | **Done** | filha, HEAD `5f5c447` | `.worktrees/26-hybrid-document-retrieval` · `feature/hybrid-document-retrieval` |
| 28-engineering-baseline-v2 | **Done** | filha, HEAD `5a2ddb2` | `.worktrees/28-engineering-baseline-v2` · `feature/engineering-baseline-v2` |
| 12b-state-backend-redis | Todo ⏸ | parqueado | futuro |
| (pai) onda-frontier | — | integra filhas; único PR contra `main` | `.worktrees/onda-merge` · `feature/onda-frontier` |

### Onda F — Série 4 P0 (**integrada** no pai)

Entrega inicial de P0 30–34 merjada em `onda-merge` @ `87487fd` (2026-09-18). Filhas
permanecem no HEAD do slice; 30 e 33 voltaram a Todo na revisão abaixo.
Os HEADs registrados preservam o histórico da entrega inicial.

| Ticket | Kanban | Papel | Onde está o código |
|---|---|---|---|
| 30-eval-required-gates | **Feedback** | filha, HEAD `3cf8149` | `.worktrees/30-eval-required-gates` · `feature/eval-required-gates` |
| 31-eval-run-selection | **Done** | filha, HEAD `78c763a` | `.worktrees/31-eval-run-selection` · `feature/eval-run-selection` |
| 32-eval-typed-http | **Done** | filha, HEAD `59b7e87` | `.worktrees/32-eval-typed-http` · `feature/eval-typed-http` |
| 33-required-review-gate | **Feedback** | filha, HEAD `4db3fa1` | `.worktrees/33-required-review-gate` · `feature/required-review-gate` |
| 34-cli-failure-exit | **Done** | filha, HEAD `addea9a` | `.worktrees/34-cli-failure-exit` · `feature/cli-failure-exit` |
| (pai) onda-frontier | — | P0 integrado @ `87487fd` | `.worktrees/onda-merge` · `feature/onda-frontier` |

### Onda F — Série 4 P1 / regressão (**integrada** no pai)

Base: pai `87487fd`. Filhas **não** abrem PR contra `main`.

| Ticket | Kanban | Papel | Onde está o código |
|---|---|---|---|
| 35-independent-test-evidence | **Todo** | filha, HEAD `36bcbc3` | `.worktrees/35-independent-test-evidence` · `feature/independent-test-evidence` |
| 36-repair-policy | **Done** | filha, HEAD `fb4f0bc` | `.worktrees/36-repair-policy` · `feature/repair-policy` |
| 37-executor-enforcement | **Todo** | filha, HEAD `e4d458b` | `.worktrees/37-executor-enforcement` · `feature/executor-enforcement` |
| 39-case-regression-gates | **Todo** | filha, HEAD `e453a3d` | `.worktrees/39-case-regression-gates` · `feature/case-regression-gates` |
| (pai) onda-frontier | — | P1 integrado @ `b8f9b7d` | `.worktrees/onda-merge` · `feature/onda-frontier` |


### Onda F — 38 context budget (**integrada** no pai)

Base: pai `f755cec`.

| Ticket | Kanban | Papel | Onde está o código |
|---|---|---|---|
| 38-critical-context-budget | **Todo** | filha, HEAD `c1c9b11` | `.worktrees/38-critical-context-budget` · `feature/critical-context-budget` |
| (pai) onda-frontier | — | integra (após Done) | `.worktrees/onda-merge` · `feature/onda-frontier` |

## Série 4 — Conformidade com o roadmap (frontier ativa)

Incluída a pedido de Ilara em 2026-09-18, após comparação com
`prompt-less-roadmap-harness(1).md`. Base auditada:
[`7f45824`](https://github.com/ilaraca/prompt-less/commit/7f458240193d7df85e93ba6b2dfff5810018b805).
Validação da revisão: 303 testes passaram, 3 foram ignorados; CI verde.
Contraexemplos locais confirmaram lacunas que a suíte existente não rejeita.
Não houve execução real de Devin/LLM nesta revisão.

Os tickets anteriores permanecem **Done** como histórico das entregas e dos
riscos então aceitos. Os itens abaixo são novos incrementos para fechar as
garantias do roadmap; não reabrem worktrees antigas. Redis/`12b` continua
parqueado e proteção da `main` permanece fora do escopo. Os IDs são locais
ao board, não números de issues do GitHub; o detalhamento desta série está aqui.

| ID | Prioridade | Título | Kanban | Blocked by |
|----|------------|--------|--------|------------|
| 30-eval-required-gates | P0.1 | Gates obrigatórios de spec, artefatos e rastreabilidade | **Feedback** | — |
| 31-eval-run-selection | P0.1 | Seleção de resultados por run e manifesto | **Done** | — |
| 32-eval-typed-http | P0.1 | HTTP tipado por serviço e operação | **Done** | — |
| 33-required-review-gate | P0.2 | Revisão obrigatória bloqueante e auditável | **Feedback** | — |
| 34-cli-failure-exit | P0.3 | Exit code de falha e bloqueio de consumo | **Done** | — |
| 35-independent-test-evidence | P1.2 | Testes e aceites com evidência independente | **Todo** | 30, 31, 32, 33, 34 |
| 36-repair-policy | P1.2 | Reaplicar política a toda superfície de reparo | **Done** | 30, 31, 32, 33, 34 |
| 37-executor-enforcement | P1.1 | Limites efetivos durante a execução do agente | **Todo** | 30, 31, 32, 33, 34 |
| 38-critical-context-budget | P2.2 | Preservação de conteúdo crítico e custo completo | **Todo** | 35, 36, 37 |
| 39-case-regression-gates | P0.1 / P3 | Regressões por caso e experimento controlado | **Todo** | 30, 31, 32 |

### Reabertura após revisão de 2026-09-18

A pedido de Ilara, **30, 33, 35, 37, 38 e 39 voltam a Todo**.
**31, 32, 34 e 36 permanecem Done** dentro do escopo revisado.
Base da revisão: [`45df02f`](https://github.com/ilaraca/prompt-less/commit/45df02f2cf8a81d6b1883cb01c703d2fc825bb13);
376 testes passaram, 3 ignorados, CI verde, com contraexemplos adicionais.
Não houve execução de Devin autenticado ou LLM real.

As notas de reabertura em cada item e o Kanban deste board são o estado atual;
aprovações e notas de entrega anteriores (inclusive em `issues/`) são histórico
e não encerram estes ajustes. Checkboxes contrariados pela revisão foram
desmarcados; critérios já comprovados foram preservados. A reabertura do
ticket não exige reutilizar worktree antiga.

Ordem dos ajustes: 30/33 → integração 35/37 → 38/39. Dependências originais
continuam como referência de fechamento; 36 não é reaberto por depender
historicamente de itens agora em ajuste. O marco ponta a ponta segue pendente.

### Ordem de implementação e fechamento

1. Fechar P0: 30, 31, 32, 33 e 34; incorporar a parte de regressões por caso
   do 39 antes de confiar em promoção de candidatos.
2. Entregar runner com limites (37), coleta independente (35) e reparação
   limitada (36), validando a integração em uma tarefa pequena.
3. Evoluir contexto/custo (38) e concluir a parte experimental do 39 somente
   após evidências do fluxo completo. Os tickets 35–37 são pré-requisitos
   para declarar o experimento como melhoria do fluxo de implementação.

Dependências nesta tabela são condições para concluir a entrega; não exigem
execução paralela. O primeiro marco do roadmap continua **pendente** até
uma tarefa real demonstrar entrada → spec → artefatos → execução → verificação,
com reparação quando necessária, falha inequívoca e métricas registradas.

### 30 — Gates obrigatórios de avaliação

**Status atual: Feedback — ajuste pós-reabertura (`3cf8149`).**

**Revisão de 2026-09-18 — ajuste pendente:** o gate de artefatos foi corrigido, mas uma execução selada com claim sem `SourceRef` ainda recebeu `passed=True`. Validar integralmente a spec e as fontes; existência do ID do claim não basta.

- [x] Adicionar regressão em que claim sem fonte ou fonte inválida reprova no avaliador, mesmo com manifesto íntegro.

**Achado:** `score_case()` permite `spec_ok` compensar `art_ok=False`.
Um caso crítico com sinal na spec passou sem PRD/história; a dimensão de
artefatos indicava falha. Rastreabilidade só integra o gate em casos críticos.

**Implementar:** separar diagnóstico de aprovação e tornar obrigatórias as
dimensões exigidas pelo tipo de tarefa: spec validada, todos os artefatos
esperados, fontes/rastreabilidade válidas e ausência de pendências bloqueantes.
Casos de bloqueio esperado devem validar também a causa esperada.

**Aceite:**

- [x] Spec válida com qualquer artefato obrigatório ausente reprova.
- [x] Fonte inválida, rastreabilidade quebrada ou serviço incorreto reprova.
- [x] Uma dimensão obrigatória falsa nunca é compensada por outra.
- [x] Casos negativos entram na suíte e falham pelo motivo esperado.

**Código:** `src/learning/evals.py` e testes de avaliação.

**Kanban:** Feedback · HEAD filha `3cf8149` · ver
`issues/30-eval-required-gates.md` § Implementation note.

### 31 — Seleção por execução

**Achado:** `_load_specs()` e `_load_final_artifacts()` usam busca recursiva
sem seleção pelo manifesto. Uma spec em `runs/old` fez uma avaliação de
`run_id=new` passar no contraexemplo local.

**Implementar:** exigir a identidade da execução e carregar apenas artefatos
registrados no respectivo manifesto, verificando estado e integridade.
Espelhos de compatibilidade não participam da seleção automática.

**Aceite:**

- [ ] Uma execução antiga correta não faz a atual passar.
- [ ] Runs simultâneas com entradas diferentes não misturam evidências.
- [ ] Manifesto ausente, run divergente ou artefato adulterado reprova.
- [ ] Run bloqueada pode ser avaliada como bloqueio esperado, mas seus
      artefatos não são liberados para implementação.

**Código:** `src/learning/evals.py`, integração com `src/runtime/run_store.py`.

### 32 — Contratos HTTP tipados

**Achado:** `collect_spec_statuses()` extrai números de RF/AC/perguntas e
não usa `operations.success_status`. Campo tipado 201 com texto contendo
200 produziu o conjunto `{200}` na verificação local.

**Implementar:** comparar método, rota, serviço, sucesso tipado e erros
vinculados à operação. Texto livre não serve como prova do contrato.

**Aceite:**

- [x] Status tipado incorreto reprova mesmo com número correto em outra seção.
- [x] Status correto em outro serviço/operação não compensa a divergência.
- [x] Sucesso ausente ou pendente não recebe valor presumido.
- [x] Fixtures declaram expectativas por operação e exercitam esses negativos.

**Código:** `src/learning/evals.py`, fixtures e modelo canônico.

### 33 — Revisão obrigatória bloqueante

**Status atual: Feedback — ajuste pós-reabertura (`4db3fa1`).**

**Revisão de 2026-09-18 — ajuste pendente:** após aprovar os vínculos, alterar o texto do requisito manteve a validação sem erros. `spec.version` permanece `1.0` e o fingerprint do claim não cobre o conteúdo do requisito.

- [x] Vincular a decisão ao hash do requisito/aceite revisado e suas evidências; mudança incompatível invalida a aprovação.
- [x] Cobrir alteração do conteúdo com mesmos IDs, claim e versão de schema.

**Achado:** `requires_review=True` em vínculo lexical gera apenas warning.
O teste `test_match_baixa_confianca_exige_revisao_sem_mudar_status` espera
validação aprovada nessa condição.

**Implementar:** diferenciar aviso informativo de revisão obrigatória e exigir
decisão explícita vinculada à versão da spec/claim antes de liberar execução.
Confiança numérica não substitui evidência nem aprovação humana.

**Aceite:**

- [x] Pendência obrigatória não resolvida bloqueia implementação.
- [x] Decisão registra responsável, justificativa e versão revisada.
- [x] Alteração da evidência/spec invalida decisão incompatível.
- [x] Avisos genuinamente informativos permanecem não bloqueantes.
- [x] Teste existente é ajustado ao contrato e cobre aprovação/rejeição.

**Código:** `src/validators/__init__.py`, modelo de revisão e testes de provenance.

**Kanban:** Feedback · HEAD filha `4db3fa1` · ver
`issues/33-required-review-gate.md` § Implementation note.

### 34 — Falha inequívoca na CLI

**Achado:** `src.run.main()` imprime o resultado e retorna normalmente.
Teste pontual com `run()` substituído por retorno `status=blocked`
confirmou saída normal; não foi uma execução E2E da pipeline bloqueada.

**Implementar:** propagar `blocked`/`failed` como exit code não zero e
manter JSON/diagnóstico legível; consumidores validam identidade e estado.

**Aceite:**

- [x] Teste de subprocesso real confirma exit code não zero em blocked/failed.
- [x] Sucesso válido mantém exit code zero.
- [x] Bloqueio impede despacho ao executor e reutilização de história antiga.
- [x] Automação recebe estado e motivo coerentes com o manifesto.

**Código:** `src/run.py` e consumidores dos artefatos.

**Kanban:** Done · HEAD `addea9a` · `feature/cli-failure-exit`

### 35 — Testes e critérios de aceite independentes

**Status atual: Todo — reaberto para ajustes a pedido de Ilara.**

**Revisão de 2026-09-18 — ajustes pendentes:** `git diff`, classificado pelo sidecar como unitário e associado aos ACs por `covers`, terminou com verificação `passed` sem executar teste comportamental. Na integração com `EnforcedRunner`, a coleta falhou com `'EnforcedRunner' object is not callable`.

- [ ] Definir verificações de aceite controladas pelo harness e validar resultados reais; `kind`/`covers` do agente não bastam.
- [ ] Rejeitar comando sem teste, ainda que autorizado e com exit code zero, como prova comportamental.
- [ ] Unificar a interface do runner e testar `DevinAdapter` + `EnforcedRunner` reais juntos, sem stub na chamada.

**Achado:** `_materialize_test_evidence()` monta JSONL a partir do sidecar do
agente; `passed=True` pode virar `exit_code=0` sem execução do comando.
Isso demonstra falta de independência da evidência, não aprovação de todo o
verificador. AC sem mapeamento também gera apenas warning.

**Implementar:** executar verificações por runner controlado pelo harness,
capturar argv, stdout/stderr e exit code reais e vinculá-los a run, repositório,
commits e hash da spec. Sidecar serve apenas como sugestão. Verificar cada
aceite obrigatório com evidência de comportamento adequada.

**Aceite:**

- [x] Relato `passed=True` sozinho nunca cria evidência suficiente.
- [x] Log ausente, incompleto, adulterado ou de outra run reprova.
- [ ] AC obrigatório sem comprovação bloqueia; arquivo existente não basta.
- [x] Uma falha conhecida é detectada e uma correção real passa na reexecução.
- [x] E2E real fica registrado separadamente de stubs e testes ignorados.

**Código:** `src/executors/devin.py`, `evidence.py`, `verify.py`.

**Kanban:** Todo · HEAD filha `36bcbc3` · ver
`issues/35-independent-test-evidence.md` § Implementation note.

### 36 — Política completa no reparo

**Achado:** `build_repair_request()` filtra padrões protegidos, mas não reaplica
a política completa. Um `TEST_FAILED` com `../outside.py` entrou em
`editable_surface` no teste pontual; não houve escrita nesse caminho.

**Implementar:** validar todo caminho proposto contra perfil, tarefa e raiz
autorizada, incluindo resolução real/symlinks. Reaplicar antes de cada tentativa.

**Aceite:**

- [x] Caminhos externos, absolutos indevidos e escapes por symlink são negados.
- [x] Caminho de diagnóstico só entra se autorizado pela política da tarefa.
- [x] Arquivos a reverter ficam separados dos editáveis; IDs de RF/AC não
      são interpretados como caminhos.
- [x] Tentativas permanecem limitadas e falha persistente termina não resolvida.
- [x] Nova verificação completa ocorre após a correção.

**Código:** `src/executors/loop.py`, `policy.py`, `close_loop.py`.

**Kanban:** Done · HEAD filha `fb4f0bc` · ver
`issues/36-repair-policy.md` § Implementation note.

### 37 — Limites efetivos do executor

**Status atual: Todo — reaberto para ajustes a pedido de Ilara.**

**Revisão de 2026-09-18 — ajustes pendentes:** processo autorizado pelo runner escreveu um marcador fora do repositório temporário e terminou com exit zero. `apply_write()` não contém escritas dos processos filhos. Ao invocar Devin com `EnforcedRunner`, o adapter troca para `run_argv`, removendo os limites dessa via.

- [ ] Impor contenção efetiva aos processos filhos e só declarar capacidades verificadas; bloquear quando não disponíveis.
- [ ] Não substituir o runner com limites por execução irrestrita na invocação do agente.
- [ ] Corrigir o contrato de chamada com o adapter (em conjunto com 35) e verificar arquivos, comandos, rede e recursos durante a execução.

**Achado:** a invocação Devin usa `profile=None`; o caminho inspecionado não
demonstra controle dos comandos internos nem isolamento de rede, credenciais
e recursos. Verificação posterior não impede efeitos durante a execução.

**Implementar:** aplicar limites no runner/ambiente e documentar o contrato
com adaptadores externos. Worktree e `shell=False` não equivalem a sandbox.
Sem capacidade de aplicar limites exigidos, bloquear o despacho.

**Aceite:**

- [ ] Tarefa autorizada altera arquivo permitido, executa teste e entrega diff.
- [ ] Tentativas equivalentes fora de arquivos/comandos/argumentos permitidos
      são impedidas durante a execução.
- [ ] Rede, credenciais, processos, tempo e recursos seguem os limites
      declarados, com testes de enforcement.
- [ ] Comandos internos relevantes são coletados pelo mecanismo confiável.
- [ ] Integração externa explicita quais garantias aplica e apresenta evidências.

**Código:** `src/executors/devin.py`, `safe_exec.py`, `policy.py` e runner.

### 38 — Contexto crítico e custo completo

**Status atual: Todo — reaberto para ajustes a pedido de Ilara.**

**Revisão de 2026-09-18 — ajuste pendente:** com `critical_coverage.complete=False` e `silent_critical_loss=True`, o avaliador ainda retornou `passed=True`. O diagnóstico existe em `layer_scores`, mas não integra os gates obrigatórios.

- [ ] Tornar perda crítica incompatível com aprovação de run concluída; manter tratamento explícito de bloqueio/split esperado.
- [ ] Adicionar caso negativo com relatório de cobertura incompleta/perda silenciosa e exigir reprovação pelo motivo correto.

**Achado:** `_fit_to_budget()` corta template e consolidado por comprimento,
sem proteger explicitamente requisitos críticos. Tokenizer e recuperação
existem, mas isso não garante preservação semântica.

**Implementar:** reservar orçamento para requisitos/contratos/aceites/evidências,
registrar omissões e permitir recuperação; dividir ou bloquear quando o mínimo
crítico não couber. Medir custo e duração incluindo validação e reparos,
diferenciando estimativa de uso/cobrança observados.

**Aceite:**

- [x] Conteúdo crítico não desaparece silenciosamente ao reduzir orçamento.
- [x] Excesso do mínimo crítico gera divisão ou bloqueio com diagnóstico.
- [x] Omissões têm motivo e referência recuperável.
- [ ] Cobertura crítica permanece no conjunto de avaliação.
- [x] Métricas da tarefa incluem tentativas e não apresentam estimativa como fatura.

**Código:** `src/context_builder.py`, compressão/recuperação e telemetria.

**Kanban:** Todo · HEAD filha `c1c9b11` · ver
`issues/38-critical-context-budget.md` § Implementation note.

### 39 — Regressões por caso e aprendizado controlado

**Status atual: Todo — reaberto para ajustes a pedido de Ilara.**

**Revisão de 2026-09-18 — ajuste pendente (inspeção de código):** comparação por caso foi corrigida, mas `improve_from_verify()` só registra resultados reservados; a decisão de promoção usa a comparação dos demais casos.

- [ ] Fazer regressões/falhas críticas nos casos reservados bloquearem a promoção, preservando sua separação da orientação da mudança.
- [ ] Adicionar cenário em que o candidato melhora no conjunto de desenvolvimento e regride no holdout; promoção deve ser rejeitada.

**Achado:** a troca de um caso não crítico aprovado por reprovado, compensada
por melhora em outro, manteve `decision=accept` e `regression=False`.
Os estados individuais aparecem no relatório, mas a regressão não é marcada.

**Implementar:** identificar regressão em todo caso/dimensão, impedir compensação
silenciosa e exigir conjuntos comparáveis; casos ausentes não são ignorados.
Na etapa P3, separar casos reservados, comparar candidatos realmente distintos
sob condições equivalentes e proteger política, verificador e avaliações.

**Aceite:**

- [x] Caso aprovado → reprovado é explicitamente marcado mesmo com taxa igual.
- [ ] Regressão crítica bloqueia; qualquer tolerância não crítica é explícita,
      justificada e registrada, nunca compensação silenciosa.
- [x] Caso removido ou conjunto incompatível impede comparação conclusiva.
- [x] Experimento registra referência, candidato, diff, condições e casos reservados.
- [x] Promoção exige benefício demonstrável, sem depender de jitter de latência.
- [x] Avaliador e dados de avaliação não são alterados pelo candidato avaliado.

**Código:** `src/learning/evals.py`, `accept.py`, workspaces e apply/rollback.

**Kanban:** Todo · HEAD filha `e453a3d` · ver
`issues/39-case-regression-gates.md` § Implementation note.

## Dependências (visão histórica — séries 1–3)

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
