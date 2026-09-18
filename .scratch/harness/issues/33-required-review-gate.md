# 33-required-review-gate

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Ajuste pós-reabertura
> integrado no pai. Não reabre worktree filha.
**Blocked by:** —  
**Prioridade:** P0.2

> Detalhe canônico: `.scratch/harness/board.md` § «33 — Revisão obrigatória bloqueante».
> Worktree: `.worktrees/33-required-review-gate` · `feature/required-review-gate`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Comportamento

`requires_review=True` exige decisão humana. A decisão inclui fingerprint do
**conteúdo** do RF/AC/erro; mudança de texto com mesmos IDs →
`REQUIRED_REVIEW_STALE`.

## Aceite

- [x] Pendência obrigatória não resolvida bloqueia implementação.
- [x] Decisão registra responsável, justificativa e versão revisada.
- [x] Alteração da evidência/spec invalida decisão incompatível.
- [x] Avisos genuinamente informativos permanecem não bloqueantes.
- [x] Teste existente é ajustado ao contrato e cobre aprovação/rejeição.

## Código

`src/domain/review.py`, `src/validators/__init__.py`, testes. README + CHANGELOG.

## Implementation note

**HEAD:** `4db3fa1` · `feature/required-review-gate`. Integrado no pai
(`edd976b`). Sem push / sem PR da filha.

**O que shipou (ajuste)**
- `reviewed_subject_fingerprint` no `ReviewDecision`.
- Conteúdo alterado com mesmos IDs/claim/`spec.version` → STALE.
- README + CHANGELOG atualizados.

**Como verificar**

```bash
cd .worktrees/onda-merge
PROMPTLESS_INTEGRITY_KEY=test-integrity-key-not-for-prod \
  PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_contextual_provenance.py -q
```
