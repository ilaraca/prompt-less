# 19-contextual-provenance

**Kanban:** Done  
**Blocked by:** 18-safe-run-storage (Done)

> Aprovado por humano em 2026-09-17. Branch `feature/contextual-provenance`
> na worktree `.worktrees/19-contextual-provenance`, baseada em `origin/main`
> (`f894e1d`). Sem push. Desbloqueia `20-evidence-backed-verification` e
> `22-code-evidence-spec` (Done em 2026-09-18). `26` ainda espera `23`.
> `09` ainda espera `15`.

Fonte de escopo: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `19-contextual-provenance`.

## Comportamento entregue

Qualquer requisito ou decisão de qualquer serviço pode ser reconstruído até sua fonte,
sem colisão de IDs e com evidência de integridade.

## Contexto: o que já existe

`03-provenance-claims` (Done) entregou a primeira versão de `Claim` e `SourceRef`. Os
produtores de claim hoje são `src/doc_compress.py` (chunk + sinal lexical),
`src/rag_compress.py` (retrieve estrutural) e `src/marcar.py` (de/para por serviço).

O `18-safe-run-storage` (Done, PR [#4](https://github.com/ilaraca/prompt-less/pull/4)
merjado) é a base direta: `contextos/<id>/` como contrato único e write-temp +
`os.replace`. A cadeia HMAC deste ticket apoia-se nesse ponto de commit.

## Aceite

- [x] IDs incluem namespace de run/contexto ou são globalmente únicos
- [x] deduplicação usa identidade completa, não apenas `claim.id`
- [x] claims sintéticos recebem hash, seção e localização quando disponíveis
- [x] `selected_lines` identifica o trecho realmente usado
- [x] vínculo claim → requisito registra método e score de matching
- [x] matches de baixa confiança exigem revisão
- [x] artefatos finais registram claims utilizados
- [x] eventos e manifests usam hash chain ou manifest assinado
- [x] teste multi-contexto comprova que nenhum claim é perdido

## Métrica de sucesso

- 100% dos RFs não-baseline com fonte válida;
- 100% dos claims agregados preservados em execução multi-contexto;
- alteração manual de evento/artefato é detectada.

## Impacto no grafo

Era o gargalo da série 3. Com o Done, saem da espera: `20` e `22`.
`26` continua bloqueado por `23`. `09` continua bloqueado por `15`.

## Implementation note

Branch `feature/contextual-provenance`, worktree
`.worktrees/19-contextual-provenance`, base `origin/main` (`f894e1d`).
Sem push.

Um identificador público `id` (`CLM-0001` / `CLM-R001` / `CLM-SYN-001`);
chave `(context, id)`; `resolve_claim` fail-closed; sem `uid`/`local_id`;
HMAC com `kid` e anel de rotação; selo **depois** de `finish`, `events_tip`
= HMAC de `run_finished`. Fingerprint de dedup inclui `context` (carimbado
antes do hash), para o mesmo conteúdo em dois contextos não colapsar.

Arquivos novos: `src/domain/provenance.py`, `src/runtime/integrity.py`,
`tests/integration/test_contextual_provenance.py`.

Arquivos alterados: `src/run.py`, `src/spec/builder.py`, `src/doc_compress.py`,
`src/rag_compress.py`, `src/domain/{source_ref,spec,chunk,__init__}.py`,
`src/validators/__init__.py`, `src/renderers/__init__.py`, `src/emit.py`,
`src/runtime/{event_store,run_store,__init__}.py`,
`templates/{historia,prd}.skeleton.md`, `tests/integration/test_provenance.py`,
`README.md`, `CHANGELOG.md`.

### Commits

| Hash | Mensagem |
|---|---|
| `0aac05e` | feat: ancora proveniencia contextual com IDs, fingerprint e cadeia de hash |
| `2310c5f` | test: cobre multi-contexto, adulteracao e revisao de match |
| `9f462b3` | docs: documenta proveniencia contextual e cadeia de hash |
| `94e1902` | feat: assina a trilha de eventos e o selo com HMAC-SHA256 |
| `56db8da` | feat: restaura id publico de claim e endereca por (context, id) |
| `7a70bab` | docs: documenta id publico, fingerprint com context e rotacao HMAC |

Comando: na worktree, `PYTHONPATH=. pipeline/.venv/bin/python -m pytest -q`.

Pytest: baseline 83 passed → **98 passed**.

Riscos corrigidos:

| Antes | Agora |
|---|---|
| `id` virava `CLM-<ns>-0001` | `id` público `CLM-0001` / `CLM-R001` / `CLM-SYN-001`. Unicidade no par `(context, id)` |
| merge renomeava `id` | merge nunca mexe no `id` público |
| fingerprint sem `context` | carimba e hasheia `context`; mesmo conteúdo em dois contextos sobrevive |
| parser rígido de provenance/spec/eventos | campos novos são **aditivos** (`context`, `claim_links`, `hmac`, `kid`); `source_claims` permanece |
| evento forjado com `prev_hash` correto | HMAC-SHA256 fail-closed (`PROMPTLESS_INTEGRITY_KEY` + `kid`) |

Alias de leitura: `CLM-ms-cliente-0001` é aceito e normalizado para `CLM-0001`.
Referência explícita: `ms-cliente:CLM-0001`. Ids customizados (`CLM-Z`,
`CLM-low-0001`) não são reinterpretados.

Evidência por critério:

| Critério | Teste |
|---|---|
| IDs com namespace de contexto | `id` público estável; chave `(context, id)` — `test_multi_contexto_nao_perde_claims`, `test_leitura_aceita_id_namespaced_e_devolve_o_publico` |
| Dedup por identidade completa | `test_dedup_por_identidade_completa_preserva_colisao_de_id`, `test_dedup_preserva_mesmo_conteudo_em_contextos_distintos` |
| Sintéticos com hash/seção/locator | `test_claim_sintetico_ganha_hash_secao_e_locator` |
| `selected_lines` do trecho usado | `test_claim_has_source_ref` |
| Vínculo com método e score | `test_match_baixa_confianca_exige_revisao_sem_mudar_status` |
| Baixa confiança exige revisão | `test_match_baixa_confianca_exige_revisao_sem_mudar_status` |
| Artefatos listam claims | `test_artefatos_listam_claims_utilizados` |
| Hash chain HMAC / selo do manifest | `test_adulteracao_de_evento_e_detectada`, `test_adulteracao_de_artefato_e_detectada`, `test_evento_forjado_com_prev_hash_correto_falha_hmac`, `test_emit_sem_chave_e_fail_closed`, `test_verify_com_chave_errada_falha`, `test_events_tip_e_o_ultimo_hmac`, `test_rotacao_kid_verifica_run_antiga` |
| Multi-contexto sem perda | `test_multi_contexto_nao_perde_claims` |
