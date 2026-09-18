# 39-case-regression-gates

**Kanban:** Done  

> Aprovado por humano em 2026-09-18 (`pode seguir`). Não reabre worktree filha.
**Blocked by:** (ver board)  
**Prioridade:** P0.1/P3

> Detalhe canônico: `.scratch/harness/board.md` § «39 — Regressões por caso e aprendizado controlado».
> Worktree: `.worktrees/39-case-regression-gates` · `feature/case-regression-gates`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).
> Base do pai: `fef3f29`.

## Aceite

Ver checkboxes no board § correspondente.

## Código

Ver board. README + CHANGELOG obrigatórios.

## Implementation note

**HEAD filha:** `e453a3d` · `feature/case-regression-gates`

### O que shipou

- `compare_evals` marca pass→fail em **qualquer** caso (não só crítico), sem
  compensação silenciosa via `pass_rate` agregado.
- Dimensões `required_gates` True→False também regressam.
- Tolerância não crítica só com `justification` → `tolerances_applied`.
- Casos ausentes/extras → `comparable=false` + reject.
- `_improved` / promoção ignoram jitter de `avg_latency_ms`.
- P3: `partition_cases` / `RESERVED_CASES` (`eval_adversarial`), registro de
  experimento em `improve` (referência, candidato, diff, condições, hold-out);
  candidato bloqueado de mutar `failure-patterns` / `playbook` /
  `permission_profiles` (`ProtectedSurfaceError`).
- README + CHANGELOG atualizados.

### Como verificar

```bash
cd .worktrees/39-case-regression-gates
PYTHONPATH=. python -m pytest tests/integration/test_learning.py \
  tests/integration/test_candidate_evals.py \
  tests/integration/test_apply_rollback.py -q
# quality_gates --skip-slow: compile/lint/types/yaml/tests OK
# (audit falhou no ambiente local py3.9 vs build==1.6.1 — residual env)
```

### Residuais

- Apply em produção (`14`) ainda pode alterar `permission_profiles` (só o
  candidato sob eval é protegido).
- Hold-out default é só `eval_adversarial`; suíte completa separa o caso da
  promoção automática.
- `pip_audit` no gate local depende de Python ≥3.10 para o lock atual.
