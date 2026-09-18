# 33-required-review-gate

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.2

> Detalhe canônico: `.scratch/harness/board.md` § «33 — Revisão obrigatória bloqueante».
> Worktree: `.worktrees/33-required-review-gate` · `feature/required-review-gate`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

`requires_review=True` deixa de ser só warning: exige decisão humana
explícita (responsável, justificativa, versão da spec/claim) antes de
liberar execução. Avisos informativos permanecem não bloqueantes.

## Aceite

- [x] Pendência obrigatória não resolvida bloqueia implementação.
- [x] Decisão registra responsável, justificativa e versão revisada.
- [x] Alteração da evidência/spec invalida decisão incompatível.
- [x] Avisos genuinamente informativos permanecem não bloqueantes.
- [x] Teste existente é ajustado ao contrato e cobre aprovação/rejeição.

## Código

`src/validators/__init__.py`, modelo de revisão, testes de provenance.
README + CHANGELOG.

## Implementation note

**HEAD:** `fd89588` · branch `feature/required-review-gate` · worktree
`.worktrees/33-required-review-gate` (base `a0010dc` / `origin/main`).

**O que shipou**

- `src/domain/review.py` — `ReviewDecision` + `decide_claim_link_review` /
  `decision_matches_evidence` (ator, justificativa, `reviewed_spec_version`,
  fingerprint do claim, método/score do link)
- `src/validators/__init__.py` — `requires_review` em ClaimLink vira erro
  `REQUIRED_REVIEW_PENDING`; rejeição → `REQUIRED_REVIEW_REJECTED`;
  evidência/spec divergente → `REQUIRED_REVIEW_STALE`;
  `ORPHAN_CLAIM` / `NFR_FROM_BASELINE` seguem warning
- `CanonicalSpec.review_decisions` (+ carga em `close_loop`)
- `src/spec/builder.py` — claim estruturado da mesma seção `bloqueios[i]`
  liga como `method=declared` sem revisão (evita falso positivo lexical
  sobre texto `block status=…`)
- README + CHANGELOG `[Unreleased]` atualizados
- Testes: pending / approve / reject / stale / avisos informativos em
  `tests/integration/test_contextual_provenance.py`

**Como verificar**

```bash
cd .worktrees/33-required-review-gate
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. python -m pytest tests/integration/test_contextual_provenance.py -q
```

19 passed. Suíte integration: **309 passed**, 1 skipped.

**Residuais**

- CLI dedicada para gravar `review_decisions` (hoje via modelo/spec) —
  fora do escopo; aprovação de run continua em `src.approval`
- `evals.py` intocado (irmãos 30–32)
- Sem push/PR da filha; merge no pai = humano

**Pare.** Aguardando review humana → Done.
