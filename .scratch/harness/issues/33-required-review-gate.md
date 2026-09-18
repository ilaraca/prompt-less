# 33-required-review-gate

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Aguardando review humana → Done.
**Blocked by:** —  
**Prioridade:** P0.2

> Detalhe canônico: `.scratch/harness/board.md` § «33 — Revisão obrigatória bloqueante».
> Worktree: `.worktrees/33-required-review-gate` · `feature/required-review-gate`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

`requires_review=True` exige decisão humana explícita. A decisão inclui
fingerprint do **conteúdo** do RF/AC/erro (além de claim + versão de
schema); mudança de texto com mesmos IDs invalida (`REQUIRED_REVIEW_STALE`).

## Aceite

- [x] Pendência obrigatória não resolvida bloqueia implementação.
- [x] Decisão registra responsável, justificativa e versão revisada.
- [x] Alteração da evidência/spec invalida decisão incompatível.
- [x] Avisos genuinamente informativos permanecem não bloqueantes.
- [x] Teste existente é ajustado ao contrato e cobre aprovação/rejeição.

## Código

`src/domain/review.py`, `src/validators/__init__.py`, testes de provenance.
README + CHANGELOG.

## Implementation note

**HEAD:** `4db3fa1` · `feature/required-review-gate` · worktree
`.worktrees/33-required-review-gate` (rebaseada em `origin/main` `221e032`).
Sem push / sem PR da filha.

**O que shipou (ajuste)**
- `ReviewDecision.reviewed_subject_fingerprint` — hash do texto do
  requisito/aceite/erro revisado.
- Alterar conteúdo com mesmos IDs/claim/`spec.version` →
  `REQUIRED_REVIEW_STALE`.
- Teste de regressão em `test_contextual_provenance.py`.
- README + CHANGELOG `[Unreleased]` atualizados.

**Como verificar**

```bash
cd .worktrees/33-required-review-gate
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_contextual_provenance.py -q
# → 20 passed
```

**Pare.** Aguardando review humana → Done. Depois: merge no pai; liberar 35/37.
