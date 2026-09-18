# 22-code-evidence-spec

**Kanban:** Done  
**Blocked by:** 04-spec-canonica (Done), 19-contextual-provenance (Done)

Liberado em 2026-09-17 pelo Done do `19`. Fonte de escopo:
`pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `22-code-evidence-spec`.

Claims e requisitos usam o `id` público (`CLM-0001`) e o par `(context, id)`;
não reintroduzir `uid` nem namespacar o id. Evidência de código entra como
campo aditivo no Canonical Spec.

## Comportamento entregue

História, PRD e Canonical Spec voltam a mostrar o estado atual e os gaps reais do
repositório, sem transformar heurística em fato.

## Aceite

- [x] Canonical Spec modela `current_state`, `gaps` e `code_evidence`
- [x] repo index aponta arquivo, símbolo, linha, rota e confiança
- [x] método/path/status encontrados no código podem resolver campos com origem `observed`
- [x] conflito entre regra declarada e código observado abre pergunta
- [x] história e PRD renderizam estado atual e gaps do IR (Canonical Spec)
- [x] ausência de evidência não vira “sem gaps”
- [x] teste de regressão preserva comportamento existente antes dos novos renderizadores

## Métrica de sucesso

- 100% dos gaps renderizados possuem evidência ou marcação heurística;
- zero mensagem “sem gaps” quando o índice não foi aplicado;
- conflitos regra × código aparecem como perguntas abertas.

## Implementation note

Worktree `.worktrees/22-code-evidence-spec`, branch `feature/code-evidence-spec`,
base 19 + `origin/main` (merge `8549d75`). Sem push. README + CHANGELOG atualizados.

Shipou evidência de código no Canonical Spec (`current_state`, `gaps`,
`code_evidence`) e no `repo_index` (arquivo, símbolo, linha, rota, confiança,
origem `observed`|`heuristic`). Método/path/status observados podem resolver
campos do IR; conflito regra × código vira `open_questions`. História e PRD
renderizam estado/gaps do IR; sem índice a seção declara *índice não aplicado*
e nunca “sem gaps”.

### Commits

| Hash | Mensagem |
|---|---|
| `075442a` | feat: ancora evidência de código no Canonical Spec e no índice |
| `df373fe` | test: cobre evidência de código, conflito regra × código e regressão sem índice |
| `5c31c4e` | docs: documenta estado atual, gaps e origem observed/heuristic no IR |

### Arquivos

`src/domain/spec.py`, `src/spec/evidence.py`, `src/spec/builder.py`,
`src/repo_index.py`, `src/renderers/__init__.py`,
`tests/integration/test_code_evidence_spec.py`, `README.md`, `CHANGELOG.md`.

### Como verificar

```bash
cd ".worktrees/22-code-evidence-spec"
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
```

Esperado: **119 passed**. Goldens de OpenAPI/Mermaid intactos.

### Riscos residuais — aceitos em 2026-09-18 (sem correção)

Não furam o aceite. O slice pede estado atual e gaps **sem transformar
heurística em fato**; origem já vai no IR e no render (`[observado]` /
`[heurística]` / *índice não aplicado*). Ruído de matching ≠ mentir origem.
Não reabrir o worktree por isso.

1. **Casar operação ↔ rota pelo path único** (`_match_routes` em
   `src/spec/evidence.py`). Se o índice tem **um** path, toda operação sem
   path na UI herda esse path com origem `observed`. Fica agressivo só quando
   há **várias** ações sem path e o repo (ou a extração) colapsa num path só
   — as N ações ganham o mesmo endpoint. Com paths distintos no código, o
   fallback **não** dispara (fica sub-casado, não super-casado). O path
   existia no código; o que é frágil é o **vínculo** operação↔rota. Endurecer
   (só casar por path/método explícito, ou marcar o fallback como `heuristic`)
   é polimento, não retrabalho. `24` e `27` herdam o vínculo; limitação
   documentada, não blocker.

2. **`status=NNN` genérico → gap `extra_in_code`.** O regex heurístico
   (`status=404` em log, config, etc.) pode inventar gap. O gap já sai com
   `origin=heuristic` e evidência. A métrica era “100% dos gaps com evidência
   ou marcação heurística”, não “zero falso positivo”. Aperto futuro: só
   emitir `extra_in_code` com origem `observed`, ou exigir status perto de
   uma rota. Não é aceite deste ticket.

3. **Índice só no fluxo com mapa/serviço.** Está **certo**, de propósito.
   Sem split não há `service_id` para olhar o índice; `no_split` declara
   *índice não aplicado* e nunca “sem gaps”. O teste de regressão cobre isso.
   “Corrigir” seria expandir o slice.

> Aprovado por humano em 2026-09-18. Riscos residuais aceitos (sem correção).
> Não reabre o worktree. Libera `23-candidate-evals`, `24-evidence-based-planning`
> e `27-sdd-consumer`. `28` continua esperando o `27`.
