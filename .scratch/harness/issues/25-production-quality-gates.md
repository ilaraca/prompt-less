# 25-production-quality-gates

**Kanban:** Done  
**Blocked by:** 18-safe-run-storage (Done), 20-evidence-backed-verification (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (branch
> protection no GitHub continua `protected: false`; ligar a regra é setting,
> não retrabalho). Código na `main` via o pai `feature/onda-frontier` (PR
> [#15](https://github.com/ilaraca/prompt-less/pull/15)); o pai acrescentou
> `33d1726`, `bf89c50`, `6028a0c`. O PR da filha
> [#13](https://github.com/ilaraca/prompt-less/pull/13) foi fechado em favor
> da onda. Não reabre a worktree filha.
>
> Fonte: `pipeline/docs/propostas-melhoria-limites-atuais.md` §6,
> âncora `25-production-quality-gates`. Absorve o endurecimento geral de CI
> que saiu do `12`.

## Comportamento entregue

Uma alteração de código não pode ser promovida sem passar por gates mínimos
reproduzíveis de qualidade e segurança.

## Aceite

- [x] dependências Python têm lock e atualização controlada
- [x] CI executa compile, lint, type checking e coverage mínima
- [x] CI executa testes adversariais de runtime, policy e provenance
- [x] `pip-audit` ou equivalente verifica vulnerabilidades
- [x] secrets scan e validação YAML fazem parte do gate
- [x] Actions são fixadas por SHA e têm permissões mínimas
- [x] matriz valida as versões Python oficialmente suportadas
- [x] relatórios de eval, coverage e verify são publicados como artifacts
- [x] branch protection exige o workflow e revisão humana
      → aceite residual 2026-09-18: workflow `CI` required-ready na `main`;
        regra no GitHub **não** ligada (`protected: false`). Setting, não código.

## Métrica de sucesso

- merge em branch protegida é impossível com gate obrigatório falhando;
- build é reproduzível com o lock;
- cobertura crítica por módulo é visível, não apenas percentual agregado.

## Fora de escopo

- CLI de aprovação / promote → `21-auditable-approval` (Done, mesma onda)
- Devin E2E → `10`
- Debugger / injection / golden recall → `15` (já na `main` pela mesma onda)
- Redis / infra → `12b` parqueado
- Ligar branch protection no GitHub: deixar o workflow required-ready +
  documentar o setting; não inventar proteção só em markdown como se já
  estivesse ativa.

## Implementation note

Slice original na worktree **filha** `feature/production-quality-gates`
(`.worktrees/25-production-quality-gates`, base
`feature/evidence-backed-verification`). Entrou em `main` pelo merge no pai
`.worktrees/onda-merge`. A filha permanece no HEAD do slice (`949f59b`) e
ainda documenta Python 3.9 / `--ignore-vuln` — esperado; não rebasear a
filha. Verificar contra o pai / `origin/main`.

**O que shipou (na `main`).** Lock hashed (`requirements.lock` /
`requirements-dev.lock`, pip-tools `--generate-hashes --allow-unsafe`),
recompilado em **3.10**. CI (`.github/workflows/ci.yml`): compileall, ruff,
mypy, pytest com coverage mínima **70%** (XML/JSON/HTML +
`coverage-by-module.json`), `pip-audit --strict` **sem** `--ignore-vuln`,
detect-secrets, YAML (`scripts/ci_reports.py validate-yaml` + yamllint),
smoke `plan_repos`. Actions pinadas por SHA com `permissions: contents: read`.
Matriz **Python 3.10–3.13**. Job agregador **`CI`** required-ready. Artifacts
`quality-reports-py<versão>` com eval (junit ou placeholder), coverage e
verify (placeholder `ci_no_close_loop`). Suíte adversariais **não** skipada.

**Commits do slice original.** `79adb58` feat, `62a390e` test, `949f59b` docs.
**Fixes da onda (já em `main`).** `33d1726`, `bf89c50`, `6028a0c`.

**Como verificar.**

```bash
cd .worktrees/onda-merge   # origin/main e9bdd91, não a worktree isolada do 25
PYTHONPATH=. "/Users/macbook/Library/Mobile Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python" -m pytest -q
# ruff / mypy / yaml / audit:
#   python -m ruff check src tests scripts
#   python -m mypy src
#   python scripts/ci_reports.py validate-yaml
#   python -m pip_audit --strict -r requirements-dev.lock
```

Na `main` da onda: **220 passed**. A worktree isolada ainda reporta 128.

### Riscos residuais

Olhar a `main`, não a issue antiga. O item 2 abaixo **já foi mitigado** na
onda; permanece só como histórico.

1. **`main` no remoto não está protegida.** API em 2026-09-18 01:49:
   `protected: false` (admin disponível). O check `CI` **já existe** depois
   do PR #15; a regra ainda não foi ligada. Merge em `main` não é impedido
   pelo GitHub — só pelo workflow na PR. Setting documentado no README da
   `main`. Único aceite em aberto; é decisão humana no GitHub, não código.
2. ~~**`pip-audit` ignora 8 CVEs / matriz 3.9.**~~ **Mitigado na `main`:**
   matriz 3.10–3.13, lock recompilado em 3.10, workflow sem `--ignore-vuln`.
   A worktree isolada e o README dela ainda mentem — ignorar.
3. **Coverage 70% é piso agregado.** Módulos CLI (`economia`, `marcar`,
   `improve`) podem ficar em 0%; o relatório por módulo torna isso visível.
4. **mypy relaxado em legado** (YAML/dicts). A onda passou ruff/mypy dos
   gates (`33d1726`); arquivos **novos** precisam continuar limpos. Não
   reabrir o 25 para cobrir CLI legado.

> Aprovado. Não reabre a worktree filha. Branch protection permanece
> residual (ligar no GitHub quando quiser o gate inescapável).
