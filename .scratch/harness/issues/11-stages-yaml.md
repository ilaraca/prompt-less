# 11-stages-yaml

**Kanban:** Done  
**Blocked by:** 18-safe-run-storage (Done)

> Aprovado por humano em 2026-09-18. Riscos residuais **aceitos** (sem correção
> de código). Branch `feature/stages-yaml` na worktree `.worktrees/11-stages-yaml`,
> base `origin/main` (`648f062`). Sem push. Desbloqueia `15-hardening-deep`.

## Objetivo

Transformar `config/pipeline.yaml` em orquestração real: estágios com handler, depends_on, gates e retomada.

## Aceite

- [x] protocolo `Stage` + registry de handlers
- [x] `run.py` executa grafo declarado no YAML (não só lista documental)
- [x] gates (ex.: validation.has_errors → blocked)
- [x] retomar run a partir de checkpoint/`events.jsonl`
- [x] testes: estágio isolado + falha intermediária não perde run_id

## Implementation note

Worktree `.worktrees/11-stages-yaml`, branch `feature/stages-yaml`, base `648f062`
(`origin/main` com o 18). Sem push. README + CHANGELOG atualizados.

> Aprovado. O `15-hardening-deep` sai da espera deste ticket.

### O que foi entregue

`config/pipeline.yaml` `stages:` passou a ser o DAG da run. `src/run.py` carrega o grafo, executa handlers do registry e aplica gates; o fluxo default (ingest → preprocess → split → IR → emit) permanece o mesmo para o YAML padrão. Checkpoints versionados em `runs/<id>/checkpoints/`, retomada com `--resume --run-id` (valida hashes), cancelamento deixa `manifest.status: cancelled`. Backend continua arquivo (sem Redis).

### Commits

| Hash | Mensagem |
|---|---|
| `a966b06` | feat: transforma pipeline.yaml em grafo executavel de estagios |
| `999346f` | test: cobre grafo, gates, resume e sandbox dos stages |
| `f23abba` | docs: documenta orquestracao declarativa e checkpoints |

### Arquivos

| Arquivo | O quê |
|---|---|
| `config/pipeline.yaml` | `handler`, `depends_on`, `foreach`, `gates`, `optional` |
| `src/runtime/stage.py` | protocolo `Stage`, `StageContext` (contenção de escrita), registry |
| `src/runtime/graph.py` | parse/validação do DAG (ciclo = `GraphError`) |
| `src/runtime/checkpoint.py` | `schema_version: 1`, hashes, migração de `events.jsonl` |
| `src/runtime/orchestrator.py` | retry, timeout, gates, resume, cancelamento |
| `src/runtime/handlers.py` | handlers do grafo default |
| `src/run.py` | executa o grafo; `--run-id` / `--resume` |
| `src/runtime/run_store.py` | status `cancelled`; `failed`/`cancelled` → `running` no resume |
| `tests/integration/test_stages_yaml.py` | aceite + §5 |
| `README.md`, `CHANGELOG.md` | CLI, checkpoints, limitações |

### Resultado dos testes

```
PYTHONPATH=. .venv/bin/python -m pytest -q
# 111 passed
```

### Como verificar

```bash
cd .worktrees/11-stages-yaml
PYTHONPATH=. /path/to/pipeline/.venv/bin/python -m pytest -q
PYTHONPATH=. /path/to/pipeline/.venv/bin/python -m src.run historia --dry-run --run-id demo-11
ls runs/demo-11/checkpoints/
PYTHONPATH=. /path/to/pipeline/.venv/bin/python -m src.run historia --dry-run --run-id demo-11 --resume
# → RunIdCollision se a run já completou; resume só reabre failed/cancelled/running
```

### Riscos residuais — aceitos em 2026-09-18

Não são furo de aceite. Sem correção neste ticket; não reabrir o worktree por isso.

1. **Timeout de estágio é best-effort** (thread + `shutdown(wait=False)`). O teto existe (`StageTimeout`, checkpoint `failed`), mas a thread pode continuar escrevendo depois. No YAML default **não há `timeout_s`**, então o risco só aparece se alguém ligar o teto. Isolar de verdade (subprocesso + kill) é endurecimento futuro — **não** entra no `15` nem reabre o `11`. Candidato natural: `09-live-llm` / `13-parallel-exec`, quando timeout real passar a ser usado.
2. **`--resume` reexecuta estágios idempotentes** no mesmo `run_id`. Não “pula” CPU; o ganho é o mesmo diretório e a recusa de inputs com hash diferente (`HashMismatch`). Pular checkpoint `completed` seria otimização, não débito.
3. **`completed`/`blocked` não reabrem.** Contrato do `18`: estados finais. Run bem-sucedida não aceita `--resume`; run nova = `run_id` novo. Reabrir completed seria regressão de auditoria.
4. **`repos_scan` / `repo_index` / `marcar` desligados** no YAML default. Já eram opcionais; o grafo default continua ingest → … → emit. Ligar sem handler real falha fechado. Índice real mora no `22`, não neste orquestrador.
5. **Espelho em `outputs/`** continua last-writer-wins e fora do sandbox do handler (orquestrador, não estágio). Contrato do `18`.
