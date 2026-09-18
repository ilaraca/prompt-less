# 20-evidence-backed-verification

**Kanban:** Done  
**Blocked by:** 18-safe-run-storage (Done), 19-contextual-provenance (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (sem correção
> de código). Branch `feature/evidence-backed-verification` na worktree
> `.worktrees/20-evidence-backed-verification`, base 19 + `origin/main`
> (merge `8549d75`). Sem push. `21-auditable-approval` e
> `25-production-quality-gates` já saíram da espera deste ticket (`21` Done
> em 2026-09-18). `10-devin-e2e` ainda espera `09`.

Liberado em 2026-09-17 pelo Done do `19`. Fonte de escopo:
`pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
âncora `20-evidence-backed-verification`.

Apoiar-se na trilha HMAC e no par `(context, id)` do `19`; não reinventar
escrita de run (isso é o `18`).

## Comportamento entregue

O close loop verifica o que ocorreu no repositório e no runner, não apenas o payload
declarado pelo executor.

## Aceite

- [x] `base_commit` e `result_commit` obrigatórios
- [x] verificação confirma ancestralidade e repositório
- [x] `changed_files` é calculado por Git
- [x] policy avalia o diff real e realpaths
- [x] comandos vêm de log estruturado do adapter
- [x] testes incluem comando, exit code, timestamp e artefato/log
- [x] traceability aponta para arquivos/linhas existentes no result commit
- [x] divergência entre relato e evidência gera erro
- [x] verify report inclui hashes das evidências

## Métrica de sucesso

- payload forjado não consegue ocultar arquivo fora de escopo;
- teste apenas “declarado” sem execução verificável é recusado;
- verify report reproduzível a partir do repo e dos logs.

## Implementation note

Entregue em `feature/evidence-backed-verification` (worktree
`.worktrees/20-evidence-backed-verification`). README + CHANGELOG atualizados.

**O que shipou.** `verify_execution` / `close_loop` passam a verificar o que
ocorreu no checkout Git e no JSONL do adapter, não o payload do executor.
`base_commit` e `result_commit` são obrigatórios; ancestralidade e o mesmo
repositório são confirmados; `changed_files` sai de `git diff --name-only`;
a policy avalia o diff e o realpath; comandos vêm do log estruturado; testes
exigem comando, `exit_code`, timestamp e artefato/log; rastreio RF/AC precisa
existir no `result_commit`; divergência relato×evidência é erro; o
`verify-report` inclui `evidence_hashes` (SHA-256 + HMAC via `seal_hmac` do 19).
Não reintroduz `uid` nem altera ids públicos de claim. Storage da run (18)
não foi reinventado.

**Arquivos.** `src/executors/evidence.py` (novo), `src/executors/verify.py`,
`src/executors/base.py` (`adapter_log` aditivo), `src/close_loop.py`
(`--repo`, `--adapter-log`), `config/failure-patterns.yaml` (`FP-EVIDENCE`),
`tests/integration/test_evidence_verify.py`,
`tests/integration/evidence_support.py`,
`tests/integration/test_executor_loop.py`, `README.md`, `CHANGELOG.md`.

**Como verificar.**

```bash
cd .worktrees/20-evidence-backed-verification
PYTHONPATH=. "/Users/macbook/Library/Mobile Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python" -m pytest -v --tb=short
```

CLI: `python -m src.close_loop --spec … --result … --repo <checkout> [--adapter-log adapter-log.jsonl]`.

**Pytest.** 121 passed.

**Commits.** `7ea4a1e` feat, `b69f972` test, `9f65dd0` docs. Sem push / sem PR.

### Riscos residuais — aceitos em 2026-09-18

Não são furo de aceite. Sem correção neste ticket; não reabrir o worktree por isso.

1. **Adapter Devin continua stub.** O 20 consome `--adapter-log` e recusa teste
   só declarado. Quem grava o JSONL é o runner real — **`10-devin-e2e`**.
2. **Worktree sujo vs `result_commit` não é checado.** Policy e rastreio leem o
   commit (`git diff` / `git show` / `cat-file`), não o disco. Worktree sujo
   não esconde arquivo fora de escopo. Testes do JSONL rodarem contra arquivos
   não commitados é débito do **`10`** (commitar + worktree limpo antes do
   verify).
3. **HMAC dos `evidence_hashes` exige `PROMPTLESS_INTEGRITY_KEY`.** Sem a chave,
   SHA-256 permanece e `hmac` fica nulo. Autenticidade da trilha já é
   fail-closed no 19; o `close_loop` pode rodar fora da run. Selo tamper-evident
   da aprovação é o **`21`**.

> Aprovado. `21` (Done) e `25` (In progress) já saíram da espera deste ticket.
> `10` continua bloqueado por `09`.
