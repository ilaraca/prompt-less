# 21-auditable-approval

**Kanban:** Done  
**Blocked by:** 20-evidence-backed-verification (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (sem correção
> de código). Branch `feature/auditable-approval` na worktree
> `.worktrees/21-auditable-approval`, base `feature/evidence-backed-verification`.
> Sem push. Não desbloqueia `10` (ainda espera `09`) nem `14` (ainda espera
> `23`). `25` já era irmão In progress; não foi iniciado por este ticket.
>
> Fonte: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
> âncora `21-auditable-approval`. Reusa HMAC/`seal_hmac` do 19 e o
> `verify-report` do 20; não reinventar storage (18).

## Comportamento entregue

Uma aprovação humana identifica quem aprovou exatamente qual spec, diff, commit e
relatório.

## Aceite

- [x] registro contém ator, timestamp, justificativa e origem
- [x] inclui hashes de Canonical Spec, verify report e result commit
- [x] aprovação expira se qualquer evidência mudar
- [x] rejeição também é persistida
- [x] aprovação não pode ser reutilizada em outra run
- [x] CLI separa `request-approval`, `approve` e `promote`
- [x] histórico é consultável e tamper-evident

## Métrica de sucesso

- toda promoção possui uma aprovação válida e vinculada;
- alteração de spec, diff ou resultado invalida automaticamente a aprovação.

## Fora de escopo

- Devin CLI real, gravar JSONL, worktree sujo → `10-devin-e2e`
- CI / lock / pip-audit / branch protection → `25-production-quality-gates`
- Apply de proposta em código → `14-apply-rollback` (espera este ticket + 23)
- Não reabrir o 20 para tornar `evidence_hashes.hmac` fail-closed; o selo
  tamper-evident é o **registro de aprovação** (reusa `seal_hmac` / trilha
  do 19). SHA-256 do 20 continua o binding da evidência.

## Implementation note

Entregue em `feature/auditable-approval` (worktree
`.worktrees/21-auditable-approval`). README + CHANGELOG atualizados. Sem push.

**O que shipou.** Aprovação humana deixa de ser o booleano
`close_loop --approve` (`execution.approved = True`). CLI
`python -m src.approval` separa `request-approval`, `approve` (`--reject`
persiste rejeição) e `promote`. O ledger em
`runs/<id>/validations/approval.json` (write-temp + `os.replace` do 18)
guarda ator, timestamp, justificativa, origem e binding
(`canonical_spec_sha256`, `verify_report_sha256`, `result_commit`,
`diff_sha256`), selado com `seal_hmac` / `kid` do 19 (fail-closed sem
`PROMPTLESS_INTEGRITY_KEY`). Mudar spec, verify-report/diff ou
`result_commit` expira a decisão; copiar o registro para outra run é
`ApprovalReuse`; adulterar o JSON invalida o HMAC. Promote sem aprovação
vigente e vinculada falha fechado e **não** aplica código (14).
`--approve` no `close_loop` sai com erro e aponta para `src.approval`.

**Arquivos.** `src/runtime/approval.py` (novo), `src/approval.py` (CLI),
`src/close_loop.py` (remove atalho), `src/runtime/__init__.py`,
`tests/integration/test_auditable_approval.py`,
`tests/integration/test_executor_loop.py`, `README.md`, `CHANGELOG.md`.

**Como verificar.**

```bash
cd .worktrees/21-auditable-approval
PYTHONPATH=. "/Users/macbook/Library/Mobile Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python" -m pytest -q --tb=short
```

CLI: `python -m src.approval request-approval|approve|promote|show --run-dir runs/<id> --run-id <id>`.

**Pytest.** 133 passed.

**Commits.** `ab859b7` feat, `62d41d2` test, `11dd8cd` docs. Sem push / sem PR.

### Riscos residuais — aceitos em 2026-09-18

Não são furo de aceite. Sem correção neste ticket; não reabrir o worktree por isso.

1. **Promote é só um selo, não apply.** Grava `validations/promotion.json`.
   Aplicar proposta em código continua no **`14-apply-rollback`** (ainda
   espera o `23`).
2. **Binding é aos arquivos da run, não a um segundo `git diff` no promote.**
   Spec, verify-report e `execution.json` são rehashed; o checkout Git não
   é reinspecionado. Quem muda o repo sem regenerar o relatório não passa
   pelo verify do 20. Worktree sujo vs `result_commit` permanece débito do
   **`10`**.
3. **Ledger não é JSONL append-only.** O histórico é um array reescrito
   atomicamente. HMAC do documento + de cada entrada detecta adulteração;
   duas decisões concorrentes na mesma run ainda são last-write-wins
   (worker único, como no 18).
4. **`evidence_hashes.hmac` do 20 continua opcional** (nulo sem chave). O
   selo fail-closed é o registro de aprovação, de propósito. Não reabre o 20.
5. **`execution.approved` no payload ainda existe.** `False` explícito gera
   `needs_approval` no verify; isso **não** promove. O atalho `--approve`
   que marcava `True` foi removido.

> Aprovado. Não reabre o worktree. `10` continua bloqueado por `09`.
> `14` continua bloqueado por `23` e deve consumir `src.approval` /
> `assert_promotable` (não `close_loop --approve`).
