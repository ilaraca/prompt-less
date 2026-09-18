# 15-hardening-deep

**Kanban:** Done  
**Blocked by:** 03-provenance-claims (Done), 08-ir-openapi-mermaid (Done), 11-stages-yaml (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (sem
> correção de código). Código na `main` via o pai `feature/onda-frontier`
> (PR [#15](https://github.com/ilaraca/prompt-less/pull/15)). Slice
> `98262eb`. O PR da filha
> [#14](https://github.com/ilaraca/prompt-less/pull/14) foi fechado em favor
> da onda. Não reabre a worktree filha — ela fica no slice; o pai avançou.
> Desbloqueia `09-live-llm`.
>
> Aceite original + §5 (`pipeline/docs/propostas-melhoria-limites-atuais.md`,
> âncora `15-hardening-deep`). **Fora de escopo:** análise de supply chain no
> CI (é o `25`, também já na `main`); kill real de timeout de estágio (risco
> aceito do `11`); cadeia tamper-evident de provenance (é o `19`, já na `main`
> via a mesma onda).

## Objetivo

Camada de confiança: Agent Debugger rico, scan de injection/secrets, recovery on-demand de claims, golden recall.

## Aceite

Escopo original:

- [x] debugger: `failure` / `agent_behavior` / `harness_component` / `root_cause` persistidos
- [x] scan de inputs (secrets, PII heurística, instruções suspeitas) antes do LLM
- [x] tools de recovery (`search_claims`, `get_claim`) no pacote live
- [x] fixtures golden com expected claims + métrica de recall
- [x] testes para cada subcapacidade

Adicionado pela §5 (exceto o que o board já moveu):

- [x] validação de `realpath` e symlinks em paths da policy
- [x] profiles explícitos para `bff`, `api`, `mfe`, `gtw`, `worker`, `batch` + fallback fail-closed
- [x] allowlist semântica de argumentos por comando
- [x] execução sempre com `shell=False`
- [x] testes adversariais para paths, comandos, payloads e inputs

## Implementation note

Worktree **filha** `.worktrees/15-hardening-deep`, branch `feature/hardening-deep`
(base `feature/stages-yaml` `f23abba`). Entrou em `main` pelo merge no pai
`.worktrees/onda-merge` (`feature/onda-frontier`), não por PR da filha.

A filha **não** contém os commits das irmãs nem os fixes da onda (ruff/mypy,
lock 3.10). Isso é o contrato da worktree, não descompasso. Verificar o
conjunto contra o pai / `origin/main`, não contra esta filha.

### O que foi entregue

Agent Debugger persiste `failure` / `agent_behavior` / `harness_component` /
`root_cause` em `validations/debugger.json` (pipeline e `close_loop`). Scan de
inputs (secrets, PII heurística, instruções suspeitas) corre **antes** de montar
o pacote LLM; achado `error` bloqueia (`reason: input_scan_failed`). Tools
`search_claims` / `get_claim` entram no `llm_package`. Golden recall falha se o
recall dos claims anotados cair. Policy: `realpath`/symlink, profiles
`gtw`/`worker`/`batch` + fallback fail-closed, allowlist semântica de argv,
`run_argv` sempre com `shell=False`.

### Commits do slice

| Hash      | Mensagem                                                             |
| --------- | -------------------------------------------------------------------- |
| `dc3f495` | feat: endurece policy, scan de inputs, debugger e recovery de claims |
| `96727f5` | test: cobre paths, injection, secrets, debugger e golden recall      |
| `98262eb` | docs: documenta hardening profundo e limites aceitos do 15           |

### Como verificar

```bash
cd .worktrees/onda-merge   # ou pipeline em origin/main (e9bdd91)
PYTHONPATH=. /Users/macbook/Library/Mobile\ Documents/com~apple~CloudDocs/techlead-docs/pipeline/.venv/bin/python -m pytest -q
```

Na `main` da onda: **220 passed**. A worktree isolada do 15 ainda reporta 150
e está atrás — não usar como evidência de merge.

### Riscos residuais

Não furam o aceite. O CHANGELOG da `main` só tem seção `Riscos aceitos` para
o `20`; os limites deste ticket ficam aqui.

1. **Timeout de estágio continua best-effort** (risco aceito do `11`). Isolar
   de verdade (subprocesso + kill) é candidato do `09` / `13`, não retrabalho
   deste slice.
2. **HMAC/tamper-evident não vive nesta feature isolada.** O `19` entrou na
   mesma onda; a worktree do 15 não o contém, a `main` sim.
3. **Supply chain no CI** saiu daqui de propósito (`25`). Já está na `main`.
   O README da worktree isolada ainda diz o contrário — ignorar.
4. **Scan de PII/injection é heurístico.** Bloqueia `error`; não é classificador
   de modelo. Falso negativo de prosa hostil sem padrão conhecido permanece.

### Fora de escopo (intencional)

Supply chain no CI → `25` (Done de código na `main`). Kill real de timeout →
`11`. HMAC → `19`.

> Aprovado. Não reabre a worktree filha. O `09-live-llm` ficou sem blocker
> aberto.
