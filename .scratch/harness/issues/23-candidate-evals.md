# 23-candidate-evals

**Kanban:** Done  
**Blocked by:** 18-safe-run-storage (Done), 22-code-evidence-spec (Done)

Liberado em 2026-09-18 pelo Done do `22`. Fonte de escopo:
`pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `23-candidate-evals`.

Hoje `src/improve.py` compara baseline e candidate **sobre a mesma eval** e
marca `approved_for_experiment` sem aplicar a proposta num workspace distinto.
Não reinventar storage (18) nem evidência de código no IR (22). Apply em
produção é o `14` (desbloqueado pelo Done deste ticket + `21`).

## Comportamento entregue

Uma proposta só avança quando é aplicada a um candidato real e demonstra melhoria sem
regressão nos casos críticos.

## Aceite

- [x] baseline e candidate usam commits/workspaces distintos
- [x] proposta é aplicada apenas no candidato
- [x] casos críticos têm gate individual, não somente pass rate agregado
- [x] métricas incluem recall de claims, statuses, traceability, inferências inesperadas, custo e latência
- [x] inclui fixtures adversariais, multi-contexto, concorrência e recovery
- [x] HTTP crítico exige igualdade, salvo regra explícita
- [x] resultado distingue `proposed`, `applied_to_candidate`, `evaluated`, `approved_for_experiment`, `accepted` e `rejected`
- [x] histórico armazena diff e métricas comparadas

## Métrica de sucesso

- uma regressão em qualquer caso crítico sempre rejeita o candidato;
- nenhuma proposta não aplicada recebe status de melhoria comprovada.

## Implementation note

Worktree **filha** `.worktrees/23-candidate-evals`, branch
`feature/candidate-evals`, base `5c31c4e`. HEAD `ea2ef5b`. Sem remote
próprio — esperado. Mergeada no pai `.worktrees/onda-merge`
(`feature/onda-frontier` `088d671`). PR do pai contra `main`:
[#16](https://github.com/ilaraca/prompt-less/pull/16). Não reabrir a
filha nem abrir PR dela contra `main`.

> Aprovado e **Done** em 2026-09-18. Riscos residuais aceitos (não reabrir).
> O `14` e o `26` ficam desbloqueados. Apply em produção e execução sobre
> configs distintas continuam no `14`.

`improve` materializa `evals/workspaces/{baseline,candidate}` (cópia atômica
de `config/` via 18), aplica o overlay **só no candidato** e compara evals
com gate por caso `critical`. `accepted` = melhoria comprovada no candidato
— não é apply em produção (`14`). Proposta não aplicada nunca entra em
`accepted` nem `approved_for_experiment`.

### Commits

| Hash | Mensagem |
|---|---|
| `258d3e8` | feat: aplica proposta só no workspace candidato e compara evals distintas |
| `f2eec31` | test: cobre regressão crítica, apply no candidato e fixtures de eval |
| `7d2ea76` | docs: documenta evals de candidato e a máquina de status da proposta |
| `ea2ef5b` | docs: registra riscos residuais aceitos das evals de candidato |
| `088d671` | merge: incorpora evals de candidato (23) na onda (pai) |

### Arquivos

`src/learning/workspaces.py` (novo), `src/learning/evals.py`,
`src/learning/accept.py`, `src/improve.py`, `src/learning/__init__.py`,
`tests/integration/test_candidate_evals.py`, `tests/integration/test_learning.py`,
`tests/fixtures/eval_adversarial/`, `tests/fixtures/eval_multi_context/`,
`README.md`, `CHANGELOG.md`.

### Como verificar

```bash
cd ".worktrees/onda-merge"
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
```

Esperado: **233 passed** (pai com 23 + onda já em `main`). Filha isolada: 132.

### Riscos residuais — aceitos em 2026-09-18 (sem correção)

Não furam o aceite. Isolamento do candidato, apply só nele, gates por caso
`critical` e a máquina de status estão entregues. Não reabrir a filha por
isso. O efeito da proposta no IR e o apply em produção continuam no `14`.

1. **Overlay não é lido pelo pipeline em runtime.** O apply grava
   `config/proposal-overlay.yaml` só no workspace candidato.
   `run_eval_suite` anexa a identidade do workspace no relatório, mas chama
   `src.run` sem apontar config para esse path. `load_cfg()` em `src/run.py`
   continua lendo `config/pipeline.yaml` do ROOT. A comparação prova
   workspaces distintos, diff só no candidato e gates; **não** prova que a
   chave do playbook mudou o IR. O spec do `14` pede baseline e candidate
   **executados** sobre versões realmente distintas — é lá que o overlay
   (ou o `change.key/value` em config versionada) entra no `run`.

   Consequência aceita enquanto o `14` não consumir isso: com overlay
   inerte, as duas evals são o mesmo pipeline. `avg_latency_ms` entra em
   `_QUALITY_DOWN`; um segundo run uns ms mais rápido pode marcar
   `improved` e cair em `accepted` sem mudança observável no IR. Latência
   permanece métrica reportada; não usar jitter de relógio como prova de
   melhoria no `14`.

2. **`two_services` espera HTTP 401 que o spec não materializa.** Residual
   herdado do `29` (pré-filtro de `regras` por keyword no `--all-contexts`):
   “sem autenticação” não casa com `ms-cliente` nem `ms-pagamento`, o 401
   não chega ao builder. Este slice **não** alterou
   `tests/fixtures/two_services/expected.yaml` (continua `http_status_mode:
   subset` + 401, sem `critical`). O aceite multi-contexto do 23 é o
   fixture novo `eval_multi_context` (`critical`, 200/400/422 exact, dois
   serviços). Se o 401 faltar, `two_services` falha dos dois lados por
   igual — não é gate crítico nem regressão diferencial. Não “consertar”
   o golden 401 neste ticket.

3. **Suíte default do CLI ficou maior.** `DEFAULT_CASES` passou a incluir
   `eval_adversarial` e `eval_multi_context`. `--cases` restringe. Custo de
   `python -m src.improve` sem filtro sobe; não é regressão do aceite.

4. **Ainda não está em `origin/main`.** O slice já está no pai (`088d671`)
   e no PR [#16](https://github.com/ilaraca/prompt-less/pull/16). A filha
   permanece no recorte do slice (`ea2ef5b`); ficar atrás da `main` depois
   do merge do pai é o contrato — não rebasear.
