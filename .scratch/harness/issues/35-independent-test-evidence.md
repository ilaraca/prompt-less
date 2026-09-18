# 35-independent-test-evidence

**Kanban:** Feedback  

> Ajuste pós-reabertura (2026-09-18). Aguardando review humana → Done.
**Blocked by:** 30, 31, 32, 33, 34  
**Prioridade:** P1.2

> Detalhe canônico: `.scratch/harness/board.md` § «35 — Testes e critérios de aceite independentes».
> Worktree: `.worktrees/35-independent-test-evidence` · `feature/independent-test-evidence`
> Pai: `.worktrees/onda-merge` · `feature/onda-frontier` (não abrir PR da filha).

## Aceite

- [x] Relato `passed=True` sozinho nunca cria evidência suficiente.
- [x] Log ausente/incompleto/adulterado/outra run reprova.
- [x] AC obrigatório sem comprovação bloqueia; arquivo existente não basta.
- [x] Falha conhecida detectada; correção real passa na reexecução.
- [x] E2E real separado de stubs/ignorados.

## Código

`src/executors/devin.py`, `evidence.py`, `runner.py`, `verify.py`. README + CHANGELOG.

## Implementation note

**HEAD:** `5b0a663` (+ `5430a2a` docs) · `feature/independent-test-evidence`
Sem push / sem PR da filha.

**O que shipou (ajuste)**
- Sidecar `kind`/`covers` não materializam evidência; só runners de teste.
- `git diff` (e comandos sem teste) rejeitados como prova comportamental.
- `EnforcedRunner` invocável como `run_argv`; integração Devin sem stub.
- README + CHANGELOG atualizados.

**Como verificar**

```bash
cd .worktrees/35-independent-test-evidence
PYTHONPATH=. ../../pipeline/.venv/bin/python -m pytest \
  tests/integration/test_independent_test_evidence.py \
  tests/integration/test_evidence_verify.py -q
# → 18 passed
```

**Pare.** Aguardando Done humano → merge no pai (com 37); depois 38/39.
